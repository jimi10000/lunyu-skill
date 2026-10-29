#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""代码工艺体检 - 文质彬彬（查 AI 生成代码的隐性技术债）

AI 写代码快，但有几个通病：重复造轮子（同一个工具函数写三遍）、
堆死代码（写了没用）、函数过长嵌套过深、注释复述代码。
人工 CR 只看逻辑对不对，这些「慢性病」看不出来。

codecraft 机器查四类问题：
  1. 重复代码块      —— 跨文件的相似代码块（默认 6 行起，归一化后比对）
  2. 过长函数/嵌套深  —— 函数行数超阈值、if/for 嵌套超阈值
  3. 未引用定义      —— 定义了全项目没人用的函数/类（死代码候选）
  4. 表面坏习惯      —— 注释复述代码、注释掉的大段代码、TODO 没带责任人

精度说明：正则级静态扫描，不是解析器。目的是「提示」，不是「判决」。
误报是设计的——宁可多报一条让你确认，也不漏掉一个真问题。

论语出处：《论语·雍也》「文质彬彬，然后君子」——
功能（质）与可读性（文）要配得上。这条管的是「文」这一半。

退出码: 0=无问题或仅提示 / 1=--strict 模式下发现超过阈值的问题
用法:
  python scripts/codecraft.py                      # 体检当前项目
  python scripts/codecraft.py --path src/          # 指定目录
  python scripts/codecraft.py --min-lines 8        # 重复块最小行数改成 8
  python scripts/codecraft.py --strict             # 有问题就返回 1（可挂 CI）
  python scripts/codecraft.py --json               # 机器可读
"""
import argparse
import json
import os
import re
import sys
from collections import defaultdict

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "target", "vendor", ".next", ".nuxt", "coverage",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".lunyu", ".idea", ".vscode",
    "Pods", ".gradle", ".terraform", "bin", "obj",
}
CODE_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue",
    ".java", ".kt", ".kts", ".go", ".rs", ".rb", ".php", ".cs",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".swift", ".scala",
}

DEFAULT_MIN_DUP_LINES = 6
DEFAULT_MAX_FUNC_LINES = 60
DEFAULT_MAX_NESTING = 4

# 重复块降噪：这些行不构成"业务逻辑"，一堆 import 相同不算重复代码
NOISE_RE = re.compile(
    r"^(import\s|from\s|require\(|using\s|#include|package\s|import\s*$|"
    r"\}\s*$|\{\s*$|\)\s*$|;\s*$|,\s*$|\"\"\"\s*$|'''\s*$)"
)
# 算得上是"实质代码"的行：有调用/赋值/分支/返回
SUBSTANCE_RE = re.compile(r"(=\S|\(|\)|return|if |for |while |\.|\[|;)")

# 函数/类定义
DEF_RE = {
    ".py": [r"^\s*def\s+([A-Za-z_]\w*)", r"^\s*class\s+([A-Za-z_]\w*)"],
    ".js": [r"\bfunction\s+([A-Za-z_$]\w*)", r"\bclass\s+([A-Za-z_$]\w*)"],
    ".jsx": [r"\bfunction\s+([A-Za-z_$]\w*)", r"\bclass\s+([A-Za-z_$]\w*)"],
    ".ts": [r"\bfunction\s+([A-Za-z_$]\w*)", r"\bclass\s+([A-Za-z_$]\w*)"],
    ".tsx": [r"\bfunction\s+([A-Za-z_$]\w*)", r"\bclass\s+([A-Za-z_$]\w*)"],
    ".java": [r"\bclass\s+([A-Za-z_]\w*)",
              r"\b(?:public|private|protected)\s+[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\("],
    ".kt": [r"\bfun\s+([A-Za-z_]\w*)", r"\bclass\s+([A-Za-z_]\w*)"],
    ".go": [r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"],
    ".rs": [r"\bfn\s+([A-Za-z_]\w*)"],
    ".rb": [r"\bdef\s+([A-Za-z_]\w*)"],
    ".php": [r"\bfunction\s+([A-Za-z_]\w*)"],
    ".cs": [r"\b(?:public|private|internal)\s+[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\("],
    ".swift": [r"\bfunc\s+([A-Za-z_]\w*)"],
}
# 缩进/块起始（判嵌套与函数长度）
BLOCK_OPEN_RE = re.compile(r"\b(if|for|while|switch|try|catch|with|case)\b|[{(]\s*$")
PY_FUNC_RE = re.compile(r"^(\s*)def\s+([A-Za-z_]\w*)")
BRACE_FUNC_RE = re.compile(r"^\s*(?:function|func|fun)\s+([A-Za-z_]\w*)")


def rel(path, root):
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:
        return path


def read_lines(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read().splitlines()
    except OSError:
        return []


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if os.path.splitext(name)[1].lower() in CODE_EXT:
                yield os.path.join(dirpath, name)


def norm(line):
    """归一化：去掉缩进、行尾注释和多余空白，只留代码骨架。"""
    line = line.split("//", 1)[0].split("#", 1)[0]
    return re.sub(r"\s+", " ", line).strip()


def find_duplicates(root, min_lines):
    """按连续 min_lines 行的归一化文本做 hash，跨文件比对。"""
    index = defaultdict(list)
    for path in walk(root):
        lines = read_lines(path)
        code = [norm(l) for l in lines]
        for i in range(len(code) - min_lines + 1):
            chunk = [c for c in code[i:i + min_lines] if c]
            if len(chunk) < min_lines:
                continue  # 空行太多，不算有效块
            # 降噪：import / 括号 / 引号这类骨架行超过一半就跳过
            noise = sum(1 for c in chunk if NOISE_RE.match(c))
            substance = sum(1 for c in chunk if SUBSTANCE_RE.search(c))
            if noise > len(chunk) // 2 or substance < 2:
                continue
            key = "\n".join(chunk)
            if len(key) < 40:
                continue  # 太短的骨架无意义
            index[key].append((rel(path, root), i + 1, lines[i][:100].strip()))
    dups = []
    for key, locs in index.items():
        files = {l[0] for l in locs}
        if len(locs) < 2:
            continue
        # 同一文件内相邻重复也要报（复制粘贴），跨文件必报
        dups.append({
            "lines": min_lines,
            "occurrences": len(locs),
            "files": sorted(files),
            "locations": [{"file": f, "line": n, "preview": p} for f, n, p in locs[:6]],
            "preview": "\n".join(key.split("\n")[:3]),
        })
    dups.sort(key=lambda d: (-d["occurrences"], -d["lines"]))
    return dups


def find_long_funcs(root, max_lines, max_nesting):
    """过长函数 + 嵌套过深。Python 按缩进切，花括号语言按括号配对切。"""
    issues = []
    for path in walk(root):
        ext = os.path.splitext(path)[1].lower()
        lines = read_lines(path)
        rpath = rel(path, root)
        if ext == ".py":
            cur, start, indent = None, 0, 0
            for i, line in enumerate(lines, 1):
                m = PY_FUNC_RE.match(line)
                if m:
                    if cur and i - start > max_lines:
                        issues.append({"file": rpath, "line": start, "name": cur,
                                       "length": i - start, "kind": "过长函数"})
                    cur, start, indent = m.group(2), i, len(m.group(1))
                    continue
                if cur and line.strip() and not line.strip().startswith("#"):
                    cur_indent = len(line) - len(line.lstrip())
                    if cur_indent <= indent and not line.lstrip().startswith((")", "]", "}")):
                        if i - start > max_lines:
                            issues.append({"file": rpath, "line": start, "name": cur,
                                           "length": i - start, "kind": "过长函数"})
                        cur = None
            # 收尾：文件末尾的函数没有「下一行缩进回升」可触发，必须单独结算。
            # 不补这段，恰好位于文件末尾的长函数永远查不出来——而大多数文件
            # 最后一个函数就在末尾，等于这项检查在真实项目里大面积漏报。
            if cur and len(lines) + 1 - start > max_lines:
                issues.append({"file": rpath, "line": start, "name": cur,
                               "length": len(lines) + 1 - start, "kind": "过长函数"})
            # 嵌套深度
            for i, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                ind = len(line) - len(line.lstrip())
                depth = ind // 4
                if depth > max_nesting and line.lstrip().startswith(("if ", "for ", "while ")):
                    issues.append({"file": rpath, "line": i, "name": line.strip()[:40],
                                   "length": depth, "kind": "嵌套过深"})
        else:
            depth, start, fname = 0, None, None
            for i, line in enumerate(lines, 1):
                opens = line.count("{") - line.count("}")
                if fname is None:
                    m = BRACE_FUNC_RE.match(line)
                    if m:
                        fname, start = m.group(1), i
                if fname is not None:
                    if opens > 0:
                        depth += opens
                    elif opens < 0:
                        depth += opens
                        if depth <= 0:
                            if i - start > max_lines:
                                issues.append({"file": rpath, "line": start, "name": fname,
                                               "length": i - start, "kind": "过长函数"})
                            fname, depth = None, 0
                if depth > max_nesting * 2:
                    issues.append({"file": rpath, "line": i, "name": line.strip()[:40],
                                   "length": depth, "kind": "嵌套过深"})
                    depth = 0
            # 收尾：末尾函数的右花括号可能没扫到 / 括号不配对，补一次结算，
            # 否则最后一个函数（往往正是最长的那个）永远查不出来。
            if fname is not None and len(lines) + 1 - start > max_lines:
                issues.append({"file": rpath, "line": start, "name": fname,
                               "length": len(lines) + 1 - start, "kind": "过长函数"})
    return issues


def find_unreferenced(root):
    """定义了但全项目只有定义处出现过 —— 死代码候选。"""
    defs = {}
    for path in walk(root):
        ext = os.path.splitext(path)[1].lower()
        pats = DEF_RE.get(ext)
        if not pats:
            continue
        lines = read_lines(path)
        for i, line in enumerate(lines, 1):
            for pat in pats:
                m = re.search(pat, line)
                if m:
                    name = m.group(1)
                    if name in ("main", "init", "setup", "teardown", "toString",
                                "equals", "hashCode", "__init__", "__str__"):
                        continue
                    defs.setdefault(name, []).append((rel(path, root), i))
    if not defs:
        return []
    # 统计全项目引用次数
    counts = {name: 0 for name in defs}
    for path in walk(root):
        text = "\n".join(read_lines(path))
        for name in counts:
            if name in text:
                counts[name] += text.count(name)
    dead = []
    for name, locs in defs.items():
        # 出现次数 <= 定义次数 = 只有定义处，没有别处引用
        if counts.get(name, 0) <= len(locs):
            dead.append({"name": name, "file": locs[0][0], "line": locs[0][1]})
    dead.sort(key=lambda d: (d["file"], d["line"]))
    return dead


def find_bad_habits(root):
    """注释复述代码 / 注释掉的大块代码 / TODO 不带责任人。"""
    issues = []
    for path in walk(root):
        ext = os.path.splitext(path)[1].lower()
        comment = "#" if ext == ".py" else "//"
        lines = read_lines(path)
        rpath = rel(path, root)
        commented_run = 0
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith(comment):
                body = s[len(comment):].strip()
                if re.match(r"^\w+\s*(=|===|\+=)", body) or re.match(r"^(if|for|while|return|def|class)\b", body):
                    commented_run += 1
                    if commented_run == 5:
                        issues.append({"file": rpath, "line": i - 4, "kind": "注释掉的代码块",
                                       "detail": "连续 5 行以上被注释的代码，应直接删除（git 里有历史）"})
                todo = re.search(r"TODO|FIXME|XXX", body)
                if todo and not re.search(r"TODO\s*[\(（]|\d{4}-\d{2}", body):
                    issues.append({"file": rpath, "line": i, "kind": "TODO 无主",
                                   "detail": body[:60]})
            else:
                commented_run = 0
    return issues


def main(argv=None):
    ap = argparse.ArgumentParser(description="代码工艺体检 - 文质彬彬")
    ap.add_argument("--path", default=".", help="要体检的目录（默认当前）")
    ap.add_argument("--min-lines", type=int, default=DEFAULT_MIN_DUP_LINES,
                    help="重复块最小行数（默认 6）")
    ap.add_argument("--max-func-lines", type=int, default=DEFAULT_MAX_FUNC_LINES,
                    help="函数行数阈值（默认 60）")
    ap.add_argument("--max-nesting", type=int, default=DEFAULT_MAX_NESTING,
                    help="嵌套深度阈值（默认 4）")
    ap.add_argument("--skip-dead", action="store_true", help="跳过死代码检查")
    ap.add_argument("--strict", action="store_true", help="有问题返回非零（可挂 CI）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.path)
    if not os.path.isdir(root):
        print("错误: 目录不存在: %s" % args.path, file=sys.stderr)
        return 1

    dups = find_duplicates(root, args.min_lines)
    longs = find_long_funcs(root, args.max_func_lines, args.max_nesting)
    dead = [] if args.skip_dead else find_unreferenced(root)
    habits = find_bad_habits(root)

    total = len(dups) + len(longs) + len(dead) + len(habits)

    if args.json:
        print(json.dumps({
            "root": root,
            "duplicates": dups[:50],
            "long_or_nested": longs[:50],
            "unreferenced": dead[:50],
            "bad_habits": habits[:50],
            "total": total,
        }, ensure_ascii=False, indent=2))
        return 1 if (args.strict and total) else 0

    print("=" * 60)
    print("代码工艺体检: %s" % root)
    print("=" * 60)

    if not total:
        print("\n没有发现明显的工艺问题。")
        return 0

    print("\n[重复代码块] %d 组" % len(dups))
    if dups:
        for d in dups[:10]:
            print("  出现 %d 次 × %d 行：%s" % (d["occurrences"], d["lines"], "、".join(d["files"][:3])))
            print("    %s" % d["preview"].replace("\n", " / ")[:100])
        print("  处理: 提炼公共函数。重复代码块是技术债的主要来源。")
    else:
        print("  无")
    print()

    print("[过长函数 / 嵌套过深] %d 处" % len(longs))
    if longs:
        for it in longs[:10]:
            if it["kind"] == "过长函数":
                print("  %s:%d %s() 共 %d 行" % (it["file"], it["line"], it["name"], it["length"]))
            else:
                print("  %s:%d 嵌套 %d 层 —— %s" % (it["file"], it["line"], it["length"], it["name"]))
        print("  处理: 提炼函数 / 卫语句提前返回 / 分解条件")
    else:
        print("  无")
    print()

    print("[未引用定义（死代码候选）] %d 个" % len(dead))
    if dead:
        for d in dead[:15]:
            print("  %s:%d  %s" % (d["file"], d["line"], d["name"]))
        if len(dead) > 15:
            print("  … 另有 %d 个" % (len(dead) - 15))
        print("  处理: 确认无用就删。注意：框架回调/反射调用的会误报，删前确认。")
    else:
        print("  无")
    print()

    print("[坏习惯] %d 处" % len(habits))
    if habits:
        for h in habits[:10]:
            print("  %s:%d [%s] %s" % (h["file"], h["line"], h["kind"], h.get("detail", "")))
    else:
        print("  无")

    print("\n" + "-" * 60)
    print("合计 %d 处。上面是提示不是判决，框架回调/反射调用可能误报。" % total)
    print("人工确认后再动手改；重构前先补测试（没测试别裸重构）。")
    if args.strict and total:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
