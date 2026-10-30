#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""代码定位 - 必也正名乎

论语出处：《论语·子路》「名不正则言不顺」——
放到工程里：接手一个陌生仓库，第一个卡点永远是「这功能到底在哪实现的」。
不知道在哪，就只能瞎改。impact.py 回答的是反向问题（我改了会影响谁），
本脚本回答正向问题（我要找的东西在哪）。

三种找法:
    locate --keyword "支付"      按关键词找实现（文件名优先于内容）
    locate --entry               找程序的入口点（main / index / App）
    locate --route "/api/pay"    找路由定义（Web / 移动端路由表）
    locate --config "db.host"    找配置项在哪定义、在哪被读

排序逻辑刻意偏向「最可能是实现的那个」：
文件名命中 > 定义处命中 > 普通引用，路径越浅越靠前，跳过测试和依赖目录。

退出码:
    0 = 找到（或明确没找到）
    1 = 目录不存在 / 参数错误
"""
import argparse
import os
import re
import sys

SKIP_DIRS = {".git", "node_modules", "__pycache__", "dist", "build", ".lunyu",
             "vendor", ".gradle", ".idea", ".vscode", "target", "bin", "obj",
             ".pytest_cache", "coverage", ".next", "out", "Pods", ".svn"}

SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
            ".ttf", ".eot", ".mp3", ".mp4", ".avi", ".mov", ".zip", ".tar",
            ".gz", ".jar", ".class", ".so", ".dll", ".exe", ".pdf", ".min.js",
            ".map", ".lock", ".log"}

CODE_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".go", ".rs",
            ".rb", ".php", ".cs", ".c", ".cc", ".cpp", ".h", ".hpp", ".swift",
            ".scala", ".sh", ".bash", ".vue", ".svelte", ".m", ".mm"}

CONFIG_EXT = {".json", ".yaml", ".yml", ".toml", ".ini", ".properties", ".xml",
              ".env", ".conf", ".cfg"}

ENTRY_PATTERNS = [
    (r"^if\s+__name__\s*==\s*[\"']__main__[\"']", "Python 入口"),
    (r"\bdef\s+main\s*\(", "main 函数"),
    (r"\bfunc\s+main\s*\(", "Go main"),
    (r"\bpublic\s+static\s+void\s+main\s*\(", "Java main"),
    (r"\bint\s+main\s*\(", "C/C++ main"),
    (r"\bfn\s+main\s*\(", "Rust main"),
    (r"ReactDOM\.render|createRoot\s*\(", "React 挂载点"),
    (r"\bapp\.listen\s*\(|\bserver\.listen\s*\(", "服务监听"),
    (r"@SpringBootApplication", "Spring Boot 启动类"),
    (r"\bclass\s+\w*Application\w*\s*\{", "Application 类"),
    (r"AndroidManifest|@AndroidEntryPoint", "Android 入口"),
    (r"UIApplicationMain|@main\b", "iOS/Swift 入口"),
]

ROUTE_PATTERNS = [
    (r"@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*[\"']([^\"']+)", "Spring 路由"),
    (r"\b(router|app)\.(get|post|put|delete|patch|use)\s*\(\s*[\"']([^\"']+)", "Express 路由"),
    (r"@app\.route\s*\(\s*[\"']([^\"']+)", "Flask 路由"),
    (r"\bpath\s*\(\s*[\"']([^\"']+)", "Django 路由"),
    (r"@(GET|POST|PUT|DELETE|PATCH)\s*\(\s*[\"']([^\"']+)", "Retrofit 接口"),
    (r"Route\s*\(\s*[\"']([^\"']+)", "通用 Route"),
    (r"\bScreen\s*\(\s*[\"']([^\"']+)", "移动端页面路由"),
    (r"goTo|navigate\s*\(\s*[\"']([^\"']+)", "导航跳转"),
]

DEF_PATTERNS = [
    (r"^\s*def\s+(\w+)", ".py"),
    (r"^\s*(?:public|private|protected|internal)?\s*(?:static\s+)?(?:fun|func|def)\s+(\w+)",
     ".kt"),
    (r"^\s*(?:public|private|protected)?\s*(?:static\s+)?[\w<>\[\],\s\.]+\s+(\w+)\s*\(",
     ".java"),
    (r"^\s*function\s+(\w+)", ".js"),
    (r"^\s*(?:export\s+)?(?:async\s+)?function\s+(\w+)", ".ts"),
    (r"^\s*func\s+(\w+)", ".go"),
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
    return ("test" in low or "spec" in low or "__tests__" in low)


def walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext in SKIP_EXT:
                continue
            if ext not in CODE_EXT and ext not in CONFIG_EXT and ext != "":
                continue
            yield os.path.join(dirpath, name)


def score_file_hit(name, keyword):
    """文件名命中——最高优先级，说明这个文件就是干这事的。"""
    base = os.path.splitext(name)[0]
    low_k = keyword.lower()
    if base.lower() == low_k:
        return 100
    if base.lower().startswith(low_k):
        return 80
    if low_k in base.lower():
        return 60
    return 0


def cmd_keyword(args):
    root = os.path.abspath(args.root or find_root())
    if not os.path.isdir(root):
        print("错误: 目录不存在: %s" % root, file=sys.stderr)
        return 1
    kw = args.keyword
    low_k = kw.lower()
    hits = []
    for path in walk(root):
        rpath = rel(path, root)
        name = os.path.basename(path)
        name_score = score_file_hit(name, kw)
        text = read_text(path)
        if not text:
            continue
        lines = []
        content_hits = 0
        for i, line in enumerate(text.splitlines(), 1):
            if low_k in line.lower():
                content_hits += 1
                if len(lines) < args.max_lines:
                    lines.append((i, line.strip()[:120]))
        if not name_score and not content_hits:
            continue
        # 定义处权重更高：找到「定义」才算定位到实现
        def_hit = False
        for pat, _ in DEF_PATTERNS:
            if re.search(pat, text, re.M) and any(
                    re.search(pat, l[1], re.M) and low_k in l[1].lower() for l in lines):
                def_hit = True
                break
        # 测试文件降权：定位实现时先看实现
        pen = -30 if is_test(rpath) else 0
        score = name_score + (40 if def_hit else 0) + min(content_hits, 20) \
            + pen - rpath.count("/") * 2
        hits.append({"file": rpath, "score": score, "content_hits": content_hits,
                     "is_definition": def_hit, "is_test": is_test(rpath),
                     "lines": [{"no": n, "text": t} for n, t in lines]})
    hits.sort(key=lambda h: -h["score"])
    hits = hits[:args.limit]

    if args.json:
        import json
        print(json.dumps({"keyword": kw, "root": root, "hits": hits},
                         ensure_ascii=False, indent=2))
        return 0 if hits else 0

    print("=" * 60)
    print("定位「%s」: %s" % (kw, root))
    print("=" * 60)
    if not hits:
        print("没找到。换个关键词试试（可能是缩写、别名，或者在配置里以别的名字出现）。")
        return 0
    for h in hits:
        tags = []
        if h["is_definition"]:
            tags.append("定义处")
        if h["is_test"]:
            tags.append("测试")
        print("  %s%s" % (h["file"], ("  [%s]" % " ".join(tags)) if tags else ""))
        for l in h["lines"][:3]:
            print("      %d: %s" % (l["no"], l["text"]))
    print("")
    print("共 %d 处（按「最可能是实现」排序：文件名命中 > 定义处 > 普通引用）" % len(hits))
    return 0


def cmd_entry(args):
    root = os.path.abspath(args.root or find_root())
    if not os.path.isdir(root):
        print("错误: 目录不存在: %s" % root, file=sys.stderr)
        return 1
    hits = []
    for path in walk(root):
        rpath = rel(path, root)
        text = read_text(path)
        if not text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat, label in ENTRY_PATTERNS:
                if re.search(pat, line):
                    hits.append({"file": rpath, "line": i, "kind": label,
                                 "text": line.strip()[:120]})
                    break
    # 同文件只留第一条；路径浅的优先
    seen = {}
    for h in hits:
        if h["file"] not in seen:
            seen[h["file"]] = h
    hits = sorted(seen.values(), key=lambda h: (h["file"].count("/"), h["line"]))

    if args.json:
        import json
        print(json.dumps({"root": root, "entries": hits[:args.limit]},
                         ensure_ascii=False, indent=2))
        return 0

    print("=" * 60)
    print("程序入口点: %s" % root)
    print("=" * 60)
    if not hits:
        print("没找到明显的入口。可能是库/模块项目（没有单一入口），或用了框架约定。")
        return 0
    for h in hits[:args.limit]:
        print("  %s:%d  [%s]" % (h["file"], h["line"], h["kind"]))
        print("      %s" % h["text"])
    return 0


def cmd_route(args):
    root = os.path.abspath(args.root or find_root())
    if not os.path.isdir(root):
        print("错误: 目录不存在: %s" % root, file=sys.stderr)
        return 1
    target = (args.route or "").strip().strip("/")
    hits = []
    for path in walk(root):
        rpath = rel(path, root)
        text = read_text(path)
        if not text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat, label in ROUTE_PATTERNS:
                m = re.search(pat, line)
                if not m:
                    continue
                # 捕获组里通常混着「变量名」（router / app）和「HTTP 方法」（get / Get），
                # 路由路径才是我要的。判据：以 / 开头的那个就是路径；
                # 没有 / 开头的（如 Screen("Home")）就取最后一个组。
                # 早期版本直接取第一个组，结果把 "router" 当成了路径名——过滤全失效。
                cands = [g for g in m.groups() if g]
                name = ""
                for g in cands:
                    if g.startswith("/"):
                        name = g
                        break
                if not name and cands:
                    name = cands[-1]
                if target and target.lower() not in (name or "").lower():
                    continue
                hits.append({"file": rpath, "line": i, "route": name,
                             "kind": label, "text": line.strip()[:120]})
                break
    if args.json:
        import json
        print(json.dumps({"root": root, "routes": hits[:args.limit]},
                         ensure_ascii=False, indent=2))
        return 0

    print("=" * 60)
    print("路由定位%s: %s" % ("「%s」" % target if target else "（全部）", root))
    print("=" * 60)
    if not hits:
        print("没找到%s。路由可能用注解自动生成、在配置文件里，或框架不在探测表里。"
              % ("「%s」" % target if target else ""))
        return 0
    for h in hits[:args.limit]:
        print("  %s:%d  [%s] %s" % (h["file"], h["line"], h["kind"], h["route"]))
        print("      %s" % h["text"])
    return 0


def cmd_config(args):
    root = os.path.abspath(args.root or find_root())
    if not os.path.isdir(root):
        print("错误: 目录不存在: %s" % root, file=sys.stderr)
        return 1
    key = args.config
    hits = []
    for path in walk(root):
        rpath = rel(path, root)
        ext = os.path.splitext(path)[1].lower()
        if ext not in CONFIG_EXT and ext not in CODE_EXT:
            continue
        text = read_text(path)
        if not text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if key.lower() in line.lower():
                hits.append({"file": rpath, "line": i, "text": line.strip()[:120],
                             "is_config": ext in CONFIG_EXT})
                break
    # 配置定义优先
    hits.sort(key=lambda h: (not h["is_config"], h["file"].count("/")))

    if args.json:
        import json
        print(json.dumps({"root": root, "config": hits[:args.limit]},
                         ensure_ascii=False, indent=2))
        return 0

    print("=" * 60)
    print("配置项「%s」: %s" % (key, root))
    print("=" * 60)
    if not hits:
        print("没找到。可能名字不同（缩写/大小写/环境变量形式），试试只搜一部分关键词。")
        return 0
    for h in hits[:args.limit]:
        tag = "[配置]" if h["is_config"] else "[读取处]"
        print("  %s %s:%d" % (tag, h["file"], h["line"]))
        print("      %s" % h["text"])
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="代码定位 - 必也正名乎（陌生仓库里找到东西在哪）")
    ap.add_argument("--root", help="项目根目录（默认向上找 .git）")
    ap.add_argument("--limit", type=int, default=20, help="最多显示几条（默认 20）")
    ap.add_argument("--max-lines", type=int, default=5,
                    help="每个文件最多列几行（默认 5）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--keyword", help="关键词：找实现在哪")
    g.add_argument("--entry", action="store_true", help="找程序入口点")
    g.add_argument("--route", help="路由路径：找路由定义（不给则列全部）")
    g.add_argument("--config", help="配置项：找在哪定义、在哪被读")

    args = ap.parse_args(argv)
    if args.entry:
        return cmd_entry(args)
    if args.route is not None:
        return cmd_route(args)
    if args.config:
        return cmd_config(args)
    return cmd_keyword(args)


if __name__ == "__main__":
    sys.exit(main())
