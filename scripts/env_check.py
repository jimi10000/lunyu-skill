#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境锁 - 工欲善其事，必先利其器

解决真实开发最经典的痛：「我这儿能跑，你那儿跑不起来」。
换机器、换同事、过两周版本漂移，每次都要重新试错一遍。

env_check 做两件事：
  snapshot —— 把当前工具链版本和依赖声明固化成 .lunyu/env.lock
  verify   —— 拿当前环境和 env.lock 比对，列出漂移项

论语出处：《论语·卫灵公》「工欲善其事，必先利其器」——
器不利（环境对不上），事就善不了。开工前先验器，别等跑到一半才发现版本不对。

检查范围:
  1. 工具链：python / node / npm / java / gradle / go / git / docker
  2. 依赖声明文件：package.json / requirements.txt / pyproject.toml /
     build.gradle / pom.xml / go.mod / Cargo.toml

退出码: 0=一致或无基线 / 1=发现漂移（--allow-drift 时仍返回 0）
适合接进 Step 1（接到需求先 verify）和 CI。

用法:
  python scripts/env_check.py snapshot            # 记录当前环境为基线
  python scripts/env_check.py verify              # 校验是否漂移
  python scripts/env_check.py verify --json       # 机器可读
  python scripts/env_check.py show                # 打印已有基线
  python scripts/env_check.py verify --allow-drift  # 只报告，不算失败
"""
import argparse
import json
import os
import re
import subprocess
import sys

LOCK_NAME = "env.lock"

# 工具 -> (>=2 个候选命令, 版本参数, 版本正则)
TOOLS = [
    ("python", ("python3", "python"), "--version", r"(\d+\.\d+(?:\.\d+)?)"),
    ("node", ("node",), "--version", r"v?(\d+\.\d+(?:\.\d+)?)"),
    ("npm", ("npm",), "--version", r"(\d+\.\d+(?:\.\d+)?)"),
    ("java", ("java",), "-version", r"\"?(\d+(?:\.\d+){0,2})"),
    ("gradle", ("gradle",), "--version", r"Gradle\s+(\d+\.\d+(?:\.\d+)?)"),
    ("go", ("go",), "version", r"go(\d+\.\d+(?:\.\d+)?)"),
    ("git", ("git",), "--version", r"(\d+\.\d+(?:\.\d+)?)"),
    ("docker", ("docker",), "--version", r"(\d+\.\d+(?:\.\d+)?)"),
]

# 依赖声明文件 -> 提取规则（正则, 分组含义）
MANIFESTS = {
    "package.json": (r"\"(name|version)\"\s*:\s*\"([^\"]+)\"", "kv"),
    "requirements.txt": (r"^\s*([A-Za-z0-9_.\-]+)\s*(?:[=~<>]=?\s*([0-9][^\s,;]*))?", "req"),
    "pyproject.toml": (r"^\s*([A-Za-z0-9_.\-]+)\s*=\s*\"([^\"]+)\"", "req"),
    "build.gradle": (r"^\s*(?:implementation|api)\s+['\"]([^'\"]+)['\"]", "single"),
    "pom.xml": (r"<version>([^<]+)</version>", "single"),
    "go.mod": (r"^\s*(?:require\s+)?([^\s]+)\s+(v[^\s]+)", "req"),
    "Cargo.toml": (r"^\s*([A-Za-z0-9_.\-]+)\s*=\s*\"([^\"]+)\"", "req"),
}


def find_root(start=None):
    cur = os.path.abspath(start or os.getcwd())
    probe = cur
    while True:
        if os.path.isdir(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return cur
        probe = parent


def lock_path(root):
    d = os.path.join(root, ".lunyu")
    return os.path.join(d, LOCK_NAME)


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return default


def run(cmd, args):
    """跑一条命令，拿不到就返回 None —— 没装的工具不算错。"""
    try:
        r = subprocess.run(
            [cmd] + list(args),
            capture_output=True, text=True, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = (r.stdout or "") + (r.stderr or "")
    return out.strip() or None


def probe_tools():
    """探测工具链版本。没装的返回 None 而不是报错。"""
    found = {}
    for name, cmds, arg, pat in TOOLS:
        version = None
        for c in cmds:
            out = run(c, [arg])
            if not out:
                continue
            m = re.search(pat, out)
            if m:
                version = m.group(1)
                break
        found[name] = version
    return found


def probe_manifests(root):
    """读依赖声明文件，抽关键版本号。"""
    result = {}
    for fname, (pat, kind) in MANIFESTS.items():
        path = os.path.join(root, fname)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue
        items = {}
        for m in re.finditer(pat, text, re.M):
            if kind == "kv":
                items[m.group(1)] = m.group(2)
            elif kind == "req":
                items[m.group(1)] = m.group(2) or "*"
            else:
                items[m.group(1)] = "*"
            if len(items) >= 200:  # 巨型依赖文件只取前 200 条，够比对
                break
        if items:
            result[fname] = items
    return result


def capture(root):
    return {
        "captured_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tools": probe_tools(),
        "manifests": probe_manifests(root),
    }


def diff(baseline, current):
    """比对两个快照，返回漂移列表 [(类别, 项, 基线值, 当前值)]。"""
    drifts = []
    for section in ("tools", "manifests"):
        base = (baseline or {}).get(section) or {}
        cur = (current or {}).get(section) or {}
        if section == "tools":
            for k, v in sorted(base.items()):
                cv = cur.get(k)
                if v and not cv:
                    drifts.append(("工具缺失", k, v, None))
                elif v and cv and v != cv:
                    drifts.append(("工具版本变化", k, v, cv))
        else:
            for fname, base_items in sorted(base.items()):
                cur_items = cur.get(fname)
                if cur_items is None:
                    drifts.append(("依赖文件缺失", fname, "%d 项" % len(base_items), None))
                    continue
                for dep, bv in sorted(base_items.items()):
                    cv = cur_items.get(dep)
                    if cv is None:
                        drifts.append(("依赖被移除", "%s:%s" % (fname, dep), bv, None))
                    elif bv != cv and bv != "*":
                        drifts.append(("依赖版本变化", "%s:%s" % (fname, dep), bv, cv))
    return drifts


def cmd_snapshot(args):
    root = args.root or find_root()
    data = capture(root)
    d = os.path.dirname(lock_path(root))
    if not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    with open(lock_path(root), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    if args.json:
        print(json.dumps({"root": root, "saved": lock_path(root), "data": data},
                         ensure_ascii=False, indent=2))
        return 0
    print("=" * 60)
    print("环境基线已记录: %s" % lock_path(root))
    print("=" * 60)
    print("\n[工具链]")
    for k, v in sorted(data["tools"].items()):
        print("  %-10s %s" % (k, v or "（未安装）"))
    if data["manifests"]:
        print("\n[依赖声明]")
        for fname, items in sorted(data["manifests"].items()):
            print("  %s: %d 项" % (fname, len(items)))
    print("\n下次换环境跑: python scripts/env_check.py verify")
    return 0


def cmd_verify(args):
    root = args.root or find_root()
    lp = lock_path(root)
    baseline = read_json(lp, None)
    if not baseline:
        msg = ("没有环境基线，无法校验。\n"
               "  先记录: python scripts/env_check.py snapshot")
        if args.json:
            print(json.dumps({"error": "no_baseline", "message": msg}, ensure_ascii=False))
            return 1
        print(msg)
        return 1
    current = capture(root)
    drifts = diff(baseline, current)

    if args.json:
        print(json.dumps({
            "root": root,
            "baseline_at": baseline.get("captured_at"),
            "drift_count": len(drifts),
            "drifts": [
                {"kind": k, "item": i, "baseline": b, "current": c}
                for k, i, b, c in drifts
            ],
        }, ensure_ascii=False, indent=2))
        return 0 if (not drifts or args.allow_drift) else 1

    print("=" * 60)
    print("环境校验: %s" % root)
    print("基线记录于: %s" % baseline.get("captured_at", "未知"))
    print("=" * 60)
    if not drifts:
        print("\n环境与基线一致，可以开工。")
        return 0

    print("\n发现 %d 项漂移：\n" % len(drifts))
    for kind, item, b, c in drifts:
        print("  [%s] %s" % (kind, item))
        print("      基线: %s" % (b if b is not None else "无"))
        print("      当前: %s" % (c if c is not None else "无"))
    print("\n处理: 确认是有意升级就重记基线 python scripts/env_check.py snapshot；"
          "否则先把环境对齐再开工。")
    if args.allow_drift:
        print("（--allow-drift：只报告，不算失败）")
        return 0
    return 1


def cmd_show(args):
    root = args.root or find_root()
    data = read_json(lock_path(root), None)
    if not data:
        print("还没有环境基线。先跑: python scripts/env_check.py snapshot")
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="环境锁 - 工欲善其事，必先利其器")
    ap.add_argument("--root", help="项目根目录（默认向上找 .git）")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("snapshot", help="记录当前环境为基线")
    p.add_argument("--root", help="项目根目录")
    p.add_argument("--json", action="store_true", help="机器可读输出")

    p = sub.add_parser("verify", help="校验当前环境是否漂移")
    p.add_argument("--root", help="项目根目录")
    p.add_argument("--json", action="store_true", help="机器可读输出")
    p.add_argument("--allow-drift", action="store_true", help="只报告不算失败")

    p = sub.add_parser("show", help="打印已有基线")
    p.add_argument("--root", help="项目根目录")

    args = ap.parse_args(argv)
    if args.cmd == "snapshot":
        return cmd_snapshot(args)
    if args.cmd == "verify":
        return cmd_verify(args)
    if args.cmd == "show":
        return cmd_show(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
