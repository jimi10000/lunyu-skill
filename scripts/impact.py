#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""影响面分析 - 欲速则不达（改存量代码前先看清谁在用它）

解决 AI 改代码最大的隐性风险：AI 看得见你给它的文件，看不见整个工程的调用网。
改一个函数不知道谁在调，改完本地通过、上线三个模块挂；或者反过来不敢删，
因为不知道有没有人用。

impact 做一件事：给定目标（文件 / 目录 / 符号），扫出全部引用点，分类列出。

分类:
  定义处    —— 符号在哪些文件里定义（同名多处定义要警惕）
  代码引用  —— 哪些源文件 import / 调用了这个符号
  测试覆盖  —— 哪些测试文件引用了它（没有 = 改动无测试保护）
  配置引用  —— 配置文件 / 路由 / 清单里的字符串引用（容易漏）
  跨仓库    —— --repos 指定其他仓库目录时的引用（改 SDK 影响下游）

支持语言（正则粗扫，零依赖）：Python / JS-TS / Java-Kotlin / Go / Shell / C 系
精度说明：这是静态文本扫描，不是解析器。目的是「不漏」，宁可多报不要漏报。

论语出处：《论语·子路》「欲速则不达」——
图快直接改，结果因为漏了调用方返工，反而更慢。动手前先看清楚。

退出码: 0=完成（无论有无引用） / 1=目标不存在或参数错误
用法:
  python scripts/impact.py --file src/pay.py             # 分析整个文件
  python scripts/impact.py --symbol refund               # 分析单个符号
  python scripts/impact.py --file src/pay.py --md         # 输出 markdown
  python scripts/impact.py --symbol refund --repos ../app # 跨仓库一起扫
  python scripts/impact.py --file src/pay.py --json
"""
import argparse
import json
import os
import re
import sys

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", "target", "vendor", ".next", ".nuxt", "coverage",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".lunyu", ".idea", ".vscode",
    "Pods", ".gradle", ".terraform", "bin", "obj",
}
SCAN_EXT = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue",
    ".java", ".kt", ".kts", ".go", ".rs", ".rb", ".php", ".cs",
    ".c", ".cc", ".cpp", ".h", ".hpp", ".swift", ".scala", ".sh", ".bash",
}
CONFIG_EXT = {
    ".json", ".yaml", ".yml", ".toml", ".xml", ".properties", ".gradle",
    ".ini", ".cfg", ".conf", ".env",
}
TEST_HINT = ("test", "spec", "__tests__", "tests/", "test_", "_test.", ".test.", ".spec.")

# 符号定义正则（按扩展名）
DEF_PATTERNS = {
    ".py": [r"^\s*def\s+([A-Za-z_]\w*)", r"^\s*class\s+([A-Za-z_]\w*)"],
    ".js": [r"\bfunction\s+([A-Za-z_$]\w*)", r"\bclass\s+([A-Za-z_$]\w*)",
            r"\b(?:const|let|var)\s+([A-Za-z_$]\w*)\s*=\s*(?:async\s*)?\("],
    ".jsx": [r"\bfunction\s+([A-Za-z_$]\w*)", r"\bclass\s+([A-Za-z_$]\w*)"],
    ".ts": [r"\bfunction\s+([A-Za-z_$]\w*)", r"\bclass\s+([A-Za-z_$]\w*)",
            r"\b(?:const|let|var)\s+([A-Za-z_$]\w*)\s*(?::[^=]+)?=\s*(?:async\s*)?\("],
    ".tsx": [r"\bfunction\s+([A-Za-z_$]\w*)", r"\bclass\s+([A-Za-z_$]\w*)"],
    ".java": [r"\b(?:public|private|protected)?\s*(?:static\s+)?[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\(",
              r"\bclass\s+([A-Za-z_]\w*)"],
    ".kt": [r"\bfun\s+([A-Za-z_]\w*)", r"\bclass\s+([A-Za-z_]\w*)"],
    ".go": [r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)"],
    ".rs": [r"\bfn\s+([A-Za-z_]\w*)"],
    ".rb": [r"\bdef\s+([A-Za-z_]\w*)"],
    ".php": [r"\bfunction\s+([A-Za-z_]\w*)"],
    ".cs": [r"\b(?:public|private|internal)?\s*[\w<>\[\]]+\s+([A-Za-z_]\w*)\s*\("],
    ".swift": [r"\bfunc\s+([A-Za-z_]\w*)"],
    ".sh": [r"^\s*([A-Za-z_]\w*)\s*\(\s*\)\s*\{"],
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


def rel(path, root):
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:
        return path


def read_text(path):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def is_test(relpath):
    low = relpath.lower()
    return any(h in low for h in TEST_HINT)


def walk(root, extra_repos=None):
    """产出 (绝对路径, 相对根, 所属仓库名, 是否主仓)。"""
    for base, tag in [(root, "main")] + [(r, os.path.basename(os.path.abspath(r)))
                                          for r in (extra_repos or [])]:
        if not os.path.isdir(base):
            continue
        base = os.path.abspath(base)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                ext = os.path.splitext(name)[1].lower()
                if ext in SCAN_EXT or ext in CONFIG_EXT:
                    p = os.path.join(dirpath, name)
                    yield p, rel(p, base), tag, base == os.path.abspath(root)


def symbols_from_file(path):
    """从目标文件抽出它定义的符号名。"""
    ext = os.path.splitext(path)[1].lower()
    pats = DEF_PATTERNS.get(ext) or DEF_PATTERNS.get(".js") or []
    text = read_text(path)
    names = []
    for pat in pats:
        for m in re.finditer(pat, text, re.M):
            n = m.group(1)
            if n and n not in names and len(n) > 1:
                names.append(n)
    # 文件名本身就是个符号（模块名），Java/Kotlin 尤其重要
    stem = os.path.splitext(os.path.basename(path))[0]
    if stem and stem not in names:
        names.insert(0, stem)
    return names


def analyze(target_symbols, root, extra_repos=None, max_hits=400):
    """扫全部文件，找出引用了任一符号的位置。"""
    buckets = {"定义处": [], "代码引用": [], "测试覆盖": [], "配置引用": []}
    cross = []
    scanned = 0
    for apath, rpath, tag, is_main in walk(root, extra_repos):
        ext = os.path.splitext(apath)[1].lower()
        text = read_text(apath)
        if not text:
            continue
        scanned += 1
        for sym in target_symbols:
            if sym not in text:
                continue
            lines = []
            for i, line in enumerate(text.splitlines(), 1):
                if sym in line:
                    snippet = line.strip()[:120]
                    lines.append((i, snippet))
                if len(lines) >= 8:
                    break
            if not lines:
                continue
            is_def = any(re.search(p, lines[0][1]) for p in (DEF_PATTERNS.get(ext) or []))
            entry = {
                "symbol": sym,
                "file": rpath,
                "repo": tag,
                "lines": [{"no": n, "text": t} for n, t in lines],
            }
            if ext in CONFIG_EXT:
                key = "配置引用"
            elif is_test(rpath):
                key = "测试覆盖"
            elif is_def:
                key = "定义处"
            else:
                key = "代码引用"
            buckets[key].append(entry)
            if not is_main:
                cross.append(entry)
            if sum(len(v) for v in buckets.values()) >= max_hits:
                return buckets, cross, scanned
    return buckets, cross, scanned


def render_text(target, symbols, buckets, cross, scanned, root, repos):
    out = []
    out.append("=" * 60)
    out.append("影响面分析: %s" % target)
    out.append("扫描范围: %s%s" % (root, (" + " + ", ".join(repos)) if repos else ""))
    out.append("=" * 60)
    out.append("\n关注符号 %d 个: %s" % (
        len(symbols), "、".join(symbols[:12]) + ("…" if len(symbols) > 12 else "")))
    out.append("（共扫过 %d 个文件）\n" % scanned)
    for key in ("定义处", "代码引用", "测试覆盖", "配置引用"):
        items = buckets.get(key) or []
        out.append("[%s] %d 处" % (key, len(items)))
        if not items:
            out.append("  无")
            if key == "测试覆盖":
                out.append("  ⚠ 没有测试覆盖这个改动面，改坏不会被测试拦住")
            out.append("")
            continue
        seen = {}
        for it in items:
            seen.setdefault(it["file"], []).append(it)
        for f, group in list(seen.items())[:30]:
            syms = sorted({g["symbol"] for g in group})
            out.append("  %s  (%s)" % (f, "、".join(syms[:5])))
            for g in group[:3]:
                for l in g["lines"][:2]:
                    out.append("      L%d: %s" % (l["no"], l["text"]))
        if len(seen) > 30:
            out.append("  … 另有 %d 个文件" % (len(seen) - 30))
        out.append("")
    if repos:
        out.append("[跨仓库引用] %d 处" % len(cross))
        if not cross:
            out.append("  无 —— 下游仓库没有引用")
        else:
            for it in cross[:20]:
                out.append("  %s :: %s" % (it["repo"], it["file"]))
        out.append("")
    out.append("---")
    out.append("动共享/公共模块前，逐条确认上面的调用方；没有测试覆盖的先补测试再改。")
    return "\n".join(out)


def render_md(target, symbols, buckets, cross, root, repos):
    out = ["# 影响面分析：%s" % target, ""]
    out.append("- 分析时间：%s" % __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    out.append("- 扫描范围：`%s`%s" % (root, (" + " + ", ".join(repos)) if repos else ""))
    out.append("- 关注符号：%s" % "、".join("`%s`" % s for s in symbols[:20]))
    out.append("")
    out.append("## 结论")
    out.append("")
    out.append("- 代码引用 %d 处，测试覆盖 %d 处，配置引用 %d 处，跨仓库 %d 处" % (
        len(buckets.get("代码引用") or []), len(buckets.get("测试覆盖") or []),
        len(buckets.get("配置引用") or []), len(cross)))
    if not buckets.get("测试覆盖"):
        out.append("- ⚠ **无测试覆盖**：改坏不会被测试拦住，先补测试再改")
    out.append("- 【待填】改动是否安全？需要通知哪些下游？")
    out.append("")
    for key in ("定义处", "代码引用", "测试覆盖", "配置引用"):
        items = buckets.get(key) or []
        out.append("## %s（%d 处）" % (key, len(items)))
        out.append("")
        if not items:
            out.append("无")
            out.append("")
            continue
        seen = {}
        for it in items:
            seen.setdefault(it["file"], []).append(it)
        out.append("| 文件 | 符号 | 行 | 内容 |")
        out.append("|---|---|---|---|")
        for f, group in list(seen.items())[:50]:
            for g in group[:3]:
                for l in g["lines"][:2]:
                    txt = l["text"].replace("|", "\\|")
                    out.append("| `%s` | `%s` | %d | %s |" % (f, g["symbol"], l["no"], txt))
        out.append("")
    if repos:
        out.append("## 跨仓库引用（%d 处）" % len(cross))
        out.append("")
        if not cross:
            out.append("下游仓库未发现引用。")
        else:
            for it in cross[:50]:
                out.append("- `%s` :: `%s` （`%s`）" % (it["repo"], it["file"], it["symbol"]))
        out.append("")
    out.append("## 改动前确认清单")
    out.append("")
    out.append("- [ ] 全部调用方已列出并评估")
    out.append("- [ ] 无测试覆盖的已补测试")
    out.append("- [ ] 配置/路由引用的已同步修改")
    out.append("- [ ] 跨仓库下游已通知")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="影响面分析 - 改存量代码前先看谁在用它")
    ap.add_argument("--file", help="目标文件（抽出它定义的符号做分析）")
    ap.add_argument("--symbol", action="append", default=[], help="目标符号（可重复）")
    ap.add_argument("--root", help="项目根目录（默认向上找 .git）")
    ap.add_argument("--repos", nargs="*", default=[], help="额外的下游仓库目录")
    ap.add_argument("--md", action="store_true", help="输出 markdown")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--out", help="写入文件（默认 stdout）")
    args = ap.parse_args(argv)

    if not args.file and not args.symbol:
        ap.error("必须给 --file 或 --symbol 之一")

    root = os.path.abspath(args.root or find_root())
    symbols = list(args.symbol)
    target = ""
    if args.file:
        fp = args.file if os.path.isabs(args.file) else os.path.join(root, args.file)
        if not os.path.exists(fp):
            print("错误: 目标文件不存在: %s" % args.file, file=sys.stderr)
            return 1
        symbols = symbols_from_file(fp) or [os.path.splitext(os.path.basename(fp))[0]]
        target = rel(fp, root)
    else:
        target = "、".join(symbols)
    # 去重保序
    seen, uniq = set(), []
    for s in symbols:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    symbols = uniq[:50]

    buckets, cross, scanned = analyze(symbols, root, args.repos)

    if args.json:
        payload = {
            "target": target,
            "root": root,
            "symbols": symbols,
            "scanned_files": scanned,
            "buckets": buckets,
            "cross_repo": cross,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    elif args.md:
        text = render_md(target, symbols, buckets, cross, root, args.repos)
    else:
        text = render_text(target, symbols, buckets, cross, scanned, root, args.repos)

    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print("已写入: %s" % args.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
