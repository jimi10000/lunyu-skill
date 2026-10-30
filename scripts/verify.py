#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完成前验证 - 证据先于声明

论语出处：《论语·公冶长》「听其言而观其行」——
听他说什么，更要看他做了什么。放到工程里：AI 说「做完了」不算数，
得拿出跑过的证据。这一步专治「声称完成实则没验证」——
这是 AI 辅助开发第一大坑，没有之一。

核心纪律：**没跑过验证命令，不许说做完了。**
本脚本不是提醒清单，是门禁：项目没有对应能力就跳过（不误报），
有对应能力却没跑过，就判定「未验证」，返回非零。

命令:
    check                     跑全部可验证项，出证据
    check --strict            有未验证项即返回 1（挂 CI / 交付前必跑）
    check --skip-tests        跳过测试执行（只检查其他项）
    record --item X --result pass|fail [--evidence "..."]
                              手工登记一项验证结果（脚本跑不到的，人要认）
    show                      查看最近一次验证证据
    require --item X          交付前要求某项必须有通过记录，没有就返回 1

退出码:
    0 = 全部通过 / 无对应能力可跳过
    1 = 有验证失败或「未验证」（--strict 下）
    2 = 参数错误
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

VERIFY_FILE = "verify.json"
HANDOVER_NAME = "HANDOVER.md"

# 测试命令探测表：(探测条件文件, 配置里是否要有 test 脚本, 命令)
TEST_PROBES = [
    ("pytest.ini", None, [sys.executable, "-m", "pytest"]),
    ("setup.cfg", None, [sys.executable, "-m", "pytest"]),
    ("pyproject.toml", None, [sys.executable, "-m", "pytest"]),
    ("tox.ini", None, [sys.executable, "-m", "pytest"]),
    ("requirements.txt", None, [sys.executable, "-m", "pytest"]),
]
# 有这些目录/文件说明是对应语言的项目
LANG_TESTS = [
    ("package.json", [("npm", "test"), ("yarn", "test"), ("pnpm", "test")]),
    ("go.mod", [("go", "test ./...")]),
    ("Cargo.toml", [("cargo", "test")]),
    ("pom.xml", [("mvn", "test")]),
    ("build.gradle", [("gradle", "test")]),
    ("build.gradle.kts", [("gradle", "test")]),
]

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".lunyu", "dist", "build",
             ".idea", ".vscode", "vendor", ".gradle", ".pytest_cache", "target"}

# Python 项目专属：这些目录/文件存在说明有测试可跑
PY_TEST_HINTS = ("tests/", "test/", "test_*.py", "*_test.py")

# 构建命令探测（可选验证项）
BUILD_PROBES = [
    ("package.json", [("npm", "run build"), ("yarn", "build")]),
    ("go.mod", [("go", "build ./...")]),
    ("Cargo.toml", [("cargo", "build --release")]),
    ("pom.xml", [("mvn", "-q package")]),
]


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


def store_path(root):
    d = os.path.join(root, ".lunyu")
    return d, os.path.join(d, VERIFY_FILE)


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def has_py_tests(root):
    """Python 项目有没有测试可跑——没测试就不误报「未验证」。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if os.path.basename(dirpath) in ("tests", "test"):
            if any(f.startswith("test_") or f.endswith("_test.py")
                   for f in filenames if f.endswith(".py")):
                return True
        if any(f.startswith("test_") or f.endswith("_test.py")
               for f in filenames if f.endswith(".py")):
            return True
    return False


def detect_test_command(root):
    """探测项目的测试命令。返回 (命令列表, 来源说明) 或 (None, None)。

    探测顺序刻意从「项目自定义」到「生态默认」：
    项目自己有 run_tests.py / Makefile test 目标的，必须用项目自己的，
    直接上 pytest 会因为发现规则不同把全绿的项目跑成失败——
    这是自动探测最容易翻车的地方。
    """
    # 1) 项目自带的测试入口（最可信）
    for name in ("tests/run_tests.py", "test/run_tests.py", "run_tests.py",
                 "tests/run.py"):
        p = os.path.join(root, name)
        if os.path.exists(p):
            return [sys.executable, name], "项目自带测试入口 %s" % name
    # 2) Makefile / justfile 里有 test 目标
    for mk in ("Makefile", "makefile", "justfile"):
        p = os.path.join(root, mk)
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("test:") or line.startswith("test "):
                            return ["make", "test"], "%s 的 test 目标" % mk
            except OSError:
                pass
    # Node / Go / Rust / Java / Kotlin：看配置文件
    for cfg, cands in LANG_TESTS:
        cfgp = os.path.join(root, cfg)
        if not os.path.exists(cfgp):
            continue
        text = ""
        try:
            with open(cfgp, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue
        if cfg == "package.json":
            try:
                scripts = (json.loads(text).get("scripts") or {})
                if "test" in scripts and "no test specified" not in scripts["test"]:
                    for runner, _ in cands:
                        return [runner, "test"], "%s 的 scripts.test" % cfg
            except ValueError:
                pass
            continue
        for runner, args in cands:
            return [runner] + args.split(), "%s 项目默认 %s test" % (cfg, runner)
    # Python：有测试文件才报
    if has_py_tests(root):
        return [sys.executable, "-m", "pytest"], "Python 项目（检测到测试文件）"
    return None, None


def detect_build_command(root):
    for cfg, cands in BUILD_PROBES:
        cfgp = os.path.join(root, cfg)
        if not os.path.exists(cfgp):
            continue
        if cfg == "package.json":
            try:
                with open(cfgp, "r", encoding="utf-8", errors="ignore") as f:
                    scripts = (json.loads(f.read()).get("scripts") or {})
                if "build" in scripts:
                    for runner, _ in cands:
                        return [runner, "run", "build"], "%s 的 scripts.build" % cfg
            except (OSError, ValueError):
                pass
            continue
        for runner, args in cands:
            return [runner] + args.split(), "%s 项目默认 %s build" % (cfg, runner)
    return None, None


def run_cmd(cmd, root, timeout=600):
    """实际执行命令，返回 (returncode, 输出尾部)。跑不动返回 (None, 原因)。"""
    try:
        proc = subprocess.run(cmd, cwd=root, capture_output=True,
                              text=True, timeout=timeout)
    except FileNotFoundError:
        return None, "命令不存在: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return None, "执行超时（%s 秒）" % timeout
    except OSError as e:
        return None, str(e)
    tail = (proc.stdout or "") + (proc.stderr or "")
    tail = "\n".join(tail.splitlines()[-15:])
    return proc.returncode, tail


def check_tests(root, run=True, timeout=600):
    """测试验证项。没测试能力=跳过；有能力没跑过=未验证。"""
    cmd, src = detect_test_command(root)
    if not cmd:
        return {"item": "tests", "status": "skip",
                "detail": "未检测到测试框架，跳过（不是每个项目都有测试）"}
    if not run:
        return {"item": "tests", "status": "unverified",
                "detail": "检测到测试命令 %s（来源 %s），但本次未执行" % (" ".join(cmd), src),
                "command": " ".join(cmd)}
    rc, out = run_cmd(cmd, root, timeout)
    if rc is None:
        return {"item": "tests", "status": "unverified",
                "detail": "测试命令跑不起来: %s" % out, "command": " ".join(cmd)}
    return {"item": "tests",
            "status": "pass" if rc == 0 else "fail",
            "exit_code": rc, "command": " ".join(cmd),
            "detail": ("测试通过" if rc == 0 else "测试失败（退出码 %d）" % rc),
            "output_tail": out}


def check_preflight(root, run=True):
    """提交前扫描：密钥/大文件/调试残留/环境配置。"""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preflight.py")
    if not os.path.exists(script):
        return {"item": "preflight", "status": "skip", "detail": "未找到 preflight.py"}
    if not run:
        return {"item": "preflight", "status": "unverified",
                "detail": "未执行提交前扫描"}
    rc, out = run_cmd([sys.executable, script, "--path", root], root, timeout=300)
    if rc is None:
        return {"item": "preflight", "status": "unverified",
                "detail": "preflight 跑不起来: %s" % out}
    # preflight: 0=通过 1=阻断 2=警告
    return {"item": "preflight",
            "status": "pass" if rc == 0 else ("warn" if rc == 2 else "fail"),
            "exit_code": rc,
            "detail": {0: "提交前扫描通过", 1: "提交前扫描阻断（有密钥/大文件等问题）",
                       2: "提交前扫描有警告"}.get(rc, "退出码 %d" % rc),
            "output_tail": out}


def check_build(root, run=True):
    cmd, src = detect_build_command(root)
    if not cmd:
        return {"item": "build", "status": "skip", "detail": "未检测到构建命令，跳过"}
    if not run:
        return {"item": "build", "status": "unverified",
                "detail": "检测到构建命令但未执行", "command": " ".join(cmd)}
    rc, out = run_cmd(cmd, root, timeout=900)
    if rc is None:
        return {"item": "build", "status": "unverified",
                "detail": "构建跑不起来: %s" % out, "command": " ".join(cmd)}
    return {"item": "build", "status": "pass" if rc == 0 else "fail",
            "exit_code": rc, "command": " ".join(cmd),
            "detail": "构建成功" if rc == 0 else "构建失败（退出码 %d）" % rc,
            "output_tail": out}


def check_handover(root):
    """交接文档：换人换 AI 接手时唯一能留下的东西。"""
    p = os.path.join(root, HANDOVER_NAME)
    if not os.path.exists(p):
        return {"item": "handover", "status": "skip",
                "detail": "项目没有 HANDOVER.md（长期项目建议有）"}
    try:
        mt = datetime.fromtimestamp(os.path.getmtime(p))
    except OSError:
        return {"item": "handover", "status": "skip", "detail": "读不到 HANDOVER.md 时间"}
    text = ""
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        pass
    if "待补" in text and text.count("待补") >= 3:
        return {"item": "handover", "status": "warn",
                "detail": "HANDOVER.md 有 %d 处「待补」，下一步未写清楚" % text.count("待补")}
    return {"item": "handover", "status": "pass",
            "detail": "交接文档已更新（%s）" % mt.strftime("%Y-%m-%d %H:%M")}


def check_known_gaps(root):
    """已知未闭环有没有声明——「过而不改，是谓过矣」。"""
    p = os.path.join(root, HANDOVER_NAME)
    if not os.path.exists(p):
        return {"item": "known_gaps", "status": "skip",
                "detail": "无 HANDOVER.md，无法检查已知未闭环声明"}
    try:
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return {"item": "known_gaps", "status": "skip", "detail": "读不到 HANDOVER.md"}
    for kw in ("已知未闭环", "已知问题", "未闭环"):
        if kw in text:
            return {"item": "known_gaps", "status": "pass",
                    "detail": "已声明已知未闭环项（%s）" % kw}
    return {"item": "known_gaps", "status": "warn",
            "detail": "未声明已知未闭环项——发现问题捂着不说比有问题更严重"}


def check_craft(root, run=True, strict=False):
    """代码工艺：重复代码块 / 过长函数 —— AI 造轮子重灾区。"""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "codecraft.py")
    if not os.path.exists(script) or not strict:
        return None  # 默认不跑，--strict 才跑（耗时）
    rc, out = run_cmd([sys.executable, script, "--path", root, "--skip-dead"],
                      root, timeout=300)
    if rc is None:
        return {"item": "craft", "status": "unverified", "detail": out}
    return {"item": "craft", "status": "pass" if rc == 0 else "warn",
            "exit_code": rc,
            "detail": "代码工艺体检通过" if rc == 0 else "代码工艺有重复块/长函数",
            "output_tail": out}


def run_all(root, skip_tests=False, skip_build=False, strict=False, timeout=600):
    items = [
        check_tests(root, run=not skip_tests, timeout=timeout),
        check_preflight(root, run=True),
    ]
    if not skip_build:
        items.append(check_build(root, run=True))
    items.append(check_handover(root))
    items.append(check_known_gaps(root))
    craft = check_craft(root, strict=strict)
    if craft:
        items.append(craft)
    return [i for i in items if i]


def summarize(items):
    """汇总：有 fail 就是失败，有 unverified 在 strict 下也是失败。"""
    counts = {"pass": 0, "fail": 0, "warn": 0, "unverified": 0, "skip": 0}
    for it in items:
        counts[it.get("status", "skip")] = counts.get(it.get("status", "skip"), 0) + 1
    return counts


def cmd_check(args):
    root = os.path.abspath(args.root or find_root())
    items = run_all(root, skip_tests=args.skip_tests, skip_build=args.skip_build,
                    strict=args.strict, timeout=args.timeout)
    counts = summarize(items)
    record = {
        "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "root": root,
        "strict": args.strict,
        "items": items,
        "summary": counts,
    }
    d, path = store_path(root)
    manual = read_json(path, {}) or {}
    # 保留手工登记项，不被自动检查覆盖
    recorded = manual.get("recorded") or {}
    if recorded:
        record["recorded"] = recorded
    write_json(path, record)

    if args.json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print("=" * 60)
        print("完成前验证: %s" % root)
        print("时间: %s" % record["verified_at"])
        print("=" * 60)
        for it in items:
            mark = {"pass": "[通过]", "fail": "[失败]", "warn": "[警告]",
                    "unverified": "[未验证]", "skip": "[跳过]"}.get(it["status"], "[?]")
            print("  %-10s %-10s %s" % (mark, it["item"], it.get("detail", "")))
            if it.get("command"):
                print("             命令: %s" % it["command"])
        print("")
        print("汇总: 通过 %d / 失败 %d / 警告 %d / 未验证 %d / 跳过 %d"
              % (counts["pass"], counts["fail"], counts["warn"],
                 counts["unverified"], counts["skip"]))
        if counts["fail"] or counts["unverified"]:
            print("")
            print("结论: 未通过 —— 有失败或「未验证」项。")
            print("  纪律: 没跑过验证命令不许说做完了。修完再跑一次。")
            return 1
        print("")
        print("结论: 通过 —— 可以声称完成，并附上本证据。")
        return 0

    # --json 模式也要给正确退出码
    if counts["fail"] or counts["unverified"]:
        return 1
    return 0


def cmd_record(args):
    """手工登记一项验证结果 —— 脚本跑不到的（UI 效果、真机实测、人工验收）。"""
    root = os.path.abspath(args.root or find_root())
    d, path = store_path(root)
    data = read_json(path, {}) or {}
    recorded = data.get("recorded") or {}
    recorded[args.item] = {
        "result": args.result,
        "evidence": args.evidence or "",
        "by": args.by or "",
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    data["recorded"] = recorded
    data["last_manual_at"] = recorded[args.item]["at"]
    if not write_json(path, data):
        print("错误: 写入失败 %s" % path, file=sys.stderr)
        return 1
    print("已登记: %s = %s" % (args.item, args.result))
    if not args.evidence:
        print("警告: 没填 --evidence。「通过」没有证据等于没验证。", file=sys.stderr)
    return 0


def cmd_show(args):
    root = os.path.abspath(args.root or find_root())
    d, path = store_path(root)
    data = read_json(path, None)
    if not data:
        print("还没有验证记录。跑: python scripts/verify.py check")
        return 1
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_require(args):
    """交付前要求某项必须有通过记录 —— 没有就阻断。"""
    root = os.path.abspath(args.root or find_root())
    d, path = store_path(root)
    data = read_json(path, None) or {}
    found = None
    for it in (data.get("items") or []):
        if it.get("item") == args.item:
            found = it
            break
    if not found:
        found = (data.get("recorded") or {}).get(args.item)
        if found:
            found = dict(found, item=args.item,
                         status="pass" if found.get("result") == "pass" else "fail")
    if not found:
        print("阻断: 没有「%s」的验证记录。先跑验证或手工登记。" % args.item)
        return 1
    if found.get("status") != "pass":
        print("阻断: 「%s」状态为 %s，不能交付。"
              % (args.item, found.get("status") or found.get("result")))
        return 1
    print("通过: 「%s」有验证记录。" % args.item)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="完成前验证 - 听其言而观其行（没跑过验证不许说做完了）")
    ap.add_argument("--root", help="项目根目录（默认向上找 .git）")
    sub = ap.add_subparsers(dest="cmd")

    c = sub.add_parser("check", help="跑全部可验证项并出证据")
    c.add_argument("--skip-tests", action="store_true", help="跳过测试执行")
    c.add_argument("--skip-build", action="store_true", help="跳过构建")
    c.add_argument("--strict", action="store_true",
                   help="严格模式：跑代码工艺体检（耗时）")
    c.add_argument("--timeout", type=int, default=600, help="单条命令超时秒数")
    c.add_argument("--json", action="store_true", help="机器可读输出")
    c.set_defaults(func=cmd_check)

    r = sub.add_parser("record", help="手工登记一项验证结果（要带证据）")
    r.add_argument("--item", required=True, help="验证项名，如 真机实测 / UI验收")
    r.add_argument("--result", required=True, choices=["pass", "fail"], help="结果")
    r.add_argument("--evidence", help="证据：截图路径、日志、复现步骤")
    r.add_argument("--by", help="谁验证的")
    r.set_defaults(func=cmd_record)

    s = sub.add_parser("show", help="查看验证证据")
    s.set_defaults(func=cmd_show)

    q = sub.add_parser("require", help="交付前要求某项必须有通过记录")
    q.add_argument("--item", required=True, help="验证项名")
    q.set_defaults(func=cmd_require)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
