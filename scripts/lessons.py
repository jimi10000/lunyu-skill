#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经验库 - 告诸往而知来者（自学习）

把踩过的坑、验证过的结论沉淀下来，下次遇到同类场景自动复用，
不再重复交学费。这是 lunyu 的「自学习」层：

  沉淀(复盘/踩坑) -> 入库 -> 检索命中 -> 应用到新需求 -> 再沉淀

特点：
  - 命中即加权：每次 search 命中会累加 hits，用得越多的经验排序越靠前，
    等于让经验库「越用越懂你」
  - 场景化检索：按关键词在 scene/problem/solution/tags 里做匹配打分
  - 可导出：一键导出 markdown，便于贴进复盘纪要或周报

存储位置: <项目根>/.lunyu/lessons.json
编号格式: L-0001 递增

用法:
  add      记一条经验
  search   检索相关经验（命中会累加 hits）
  list     列出全部（可按标签筛选）
  stats    统计概览
  export   导出 markdown 表格
"""
import argparse
import json
import os
import sys
from datetime import datetime

# 经验分类：定位问题时用得上
KINDS = ("踩坑", "结论", "偏好", "禁区", "技巧")


def find_root(start=None):
    """向上查找项目根: 优先含 .git 的目录, 否则当前目录"""
    cur = os.path.abspath(start or os.getcwd())
    probe = cur
    while True:
        if os.path.isdir(os.path.join(probe, ".git")):
            return probe
        parent = os.path.dirname(probe)
        if parent == probe:
            return cur
        probe = parent


def store_path(root=None):
    root = root or find_root()
    d = os.path.join(root, ".lunyu")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "lessons.json")


def load(path):
    if not os.path.exists(path):
        return {"next_id": 1, "lessons": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.now().strftime("%Y-%m-%d")


# ---------------- 检索打分 ----------------
def tokenize(text):
    """简单分词：英文按空格/符号切，中文按 2-gram 切，够用且不引入依赖。"""
    text = (text or "").lower()
    toks = []
    buf = ""
    for ch in text:
        if ch.isalnum():
            buf += ch
        else:
            if buf:
                toks.append(buf)
                buf = ""
    if buf:
        toks.append(buf)
    # 中文串再补 2-gram，提升「车机广播」这类短语命中率
    cn = "".join(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    for i in range(len(cn) - 1):
        toks.append(cn[i:i + 2])
    return set(toks)


def score(item, query_tokens):
    """对一条经验打分：标签权重最高，其次场景/问题，最后是结论。"""
    if not query_tokens:
        return 0.0
    scene = tokenize(item.get("scene", ""))
    problem = tokenize(item.get("problem", ""))
    solution = tokenize(item.get("solution", ""))
    tags = tokenize(" ".join(item.get("tags", [])))
    kind = tokenize(item.get("kind", ""))

    s = 0.0
    for t in query_tokens:
        if t in tags:
            s += 3.0
        if t in scene:
            s += 2.0
        if t in problem:
            s += 1.5
        if t in kind:
            s += 1.0
        if t in solution:
            s += 0.5
    # 热门经验小幅加权（越常用的越可能有用），但不让 hits 喧宾夺主
    s += min(item.get("hits", 0), 20) * 0.05
    return s


def search_items(items, query, top=5, min_score=1.0):
    """检索并按分数排序返回。"""
    qt = tokenize(query)
    scored = []
    for it in items:
        sc = score(it, qt)
        if sc >= min_score:
            scored.append((sc, it))
    scored.sort(key=lambda x: (-x[0], x[1].get("id", "")))
    return [it for _, it in scored[:top]]


# ---------------- 命令 ----------------
def cmd_add(args):
    path = store_path(args.root)
    data = load(path)
    lid = "L-%04d" % data["next_id"]
    item = {
        "id": lid,
        "kind": args.kind,
        "scene": args.scene,
        "problem": args.problem or "",
        "solution": args.solution,
        "tags": [t.strip() for t in (args.tags or "").split(",") if t.strip()],
        "source": args.source or "",
        "created_at": now(),
        "date": today(),
        "hits": 0,
    }
    data["lessons"].append(item)
    data["next_id"] += 1
    save(path, data)
    print("已记录 %s [%s] %s" % (lid, item["kind"], item["scene"]))
    print("下次检索: python scripts/lessons.py search \"%s\"" % (item["tags"][0] if item["tags"] else item["scene"]))
    return 0


def cmd_search(args):
    path = store_path(args.root)
    data = load(path)
    items = data.get("lessons", [])
    if not items:
        print("经验库为空。先记一条：python scripts/lessons.py add --scene ... --solution ...")
        return 0

    hits = search_items(items, args.query, top=args.top)
    if not hits:
        print("未检索到相关经验（关键词：%s）" % args.query)
        print("提示：这条需求本身可能就是新经验，结束后记得 add 入库。")
        return 0

    # 命中即加权：让高频经验自然浮到前面
    for it in hits:
        it["hits"] = it.get("hits", 0) + 1
    save(path, data)

    print("## 相关经验（%d 条，已按相关度排序）\n" % len(hits))
    for it in hits:
        tags = " ".join("#" + t for t in it.get("tags", []))
        print("### %s [%s] %s" % (it["id"], it.get("kind", "结论"), it.get("scene", "")))
        if it.get("problem"):
            print("- 踩坑：%s" % it["problem"])
        print("- 结论：%s" % it.get("solution", ""))
        if tags:
            print("- 标签：%s" % tags)
        if it.get("source"):
            print("- 来源：%s" % it["source"])
        print()
    print("---")
    print("用法提醒：这些是过去验证过的结论，不确定时要复核，别盲信。")
    return 0


def cmd_list(args):
    path = store_path(args.root)
    data = load(path)
    items = data.get("lessons", [])
    if args.tag:
        items = [it for it in items if args.tag in it.get("tags", [])]
    if args.kind:
        items = [it for it in items if it.get("kind") == args.kind]
    if not items:
        print("（无匹配经验）")
        return 0
    items = sorted(items, key=lambda x: (-x.get("hits", 0), x.get("id", "")))
    print("%-8s %-6s %-28s %s" % ("编号", "类型", "场景", "命中"))
    print("-" * 60)
    for it in items:
        print("%-8s %-6s %-28s %d" % (
            it["id"], it.get("kind", ""),
            (it.get("scene", "")[:26] + "..") if len(it.get("scene", "")) > 28 else it.get("scene", ""),
            it.get("hits", 0),
        ))
    return 0


def cmd_stats(args):
    path = store_path(args.root)
    data = load(path)
    items = data.get("lessons", [])
    if not items:
        print("经验库为空。")
        return 0
    by_kind = {}
    tag_count = {}
    for it in items:
        by_kind[it.get("kind", "未分类")] = by_kind.get(it.get("kind", "未分类"), 0) + 1
        for t in it.get("tags", []):
            tag_count[t] = tag_count.get(t, 0) + 1
    print("经验总数: %d" % len(items))
    print("按类型:")
    for k, v in sorted(by_kind.items(), key=lambda x: -x[1]):
        print("  %-8s %d" % (k, v))
    if tag_count:
        print("高频标签:")
        for t, v in sorted(tag_count.items(), key=lambda x: -x[1])[:10]:
            print("  #%-14s %d" % (t, v))
    total_hits = sum(it.get("hits", 0) for it in items)
    print("累计命中: %d 次（复用越多，说明沉淀越值钱）" % total_hits)
    return 0


def cmd_export(args):
    path = store_path(args.root)
    data = load(path)
    items = sorted(data.get("lessons", []), key=lambda x: (-x.get("hits", 0), x["id"]))
    lines = ["# 经验库导出\n", "| 编号 | 类型 | 场景 | 踩坑 | 结论 | 标签 | 命中 |",
             "|---|---|---|---|---|---|---|"]
    for it in items:
        cell = lambda s: (s or "").replace("|", "\\|").replace("\n", " ")
        lines.append("| %s | %s | %s | %s | %s | %s | %d |" % (
            it["id"], cell(it.get("kind")), cell(it.get("scene")),
            cell(it.get("problem")), cell(it.get("solution")),
            " ".join("#" + t for t in it.get("tags", [])), it.get("hits", 0),
        ))
    out = "\n".join(lines) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print("已导出: %s" % args.out)
    else:
        print(out, end="")
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="经验库 - 告诸往而知来者（自学习）")
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="记一条经验")
    a.add_argument("--scene", required=True, help="什么场景（如：车机静态广播）")
    a.add_argument("--solution", required=True, help="结论/正确做法")
    a.add_argument("--problem", help="踩过的坑（错在哪）")
    a.add_argument("--tags", help="标签，逗号分隔（如：android,车机,广播）")
    a.add_argument("--kind", choices=KINDS, default="结论", help="类型")
    a.add_argument("--source", help="来源（如：哪吒车机实测）")
    a.add_argument("--root", help="项目根目录")
    a.set_defaults(func=cmd_add)

    s = sub.add_parser("search", help="检索相关经验（命中累加 hits）")
    s.add_argument("query", help="关键词/场景描述")
    s.add_argument("--top", type=int, default=5, help="返回条数")
    s.add_argument("--root", help="项目根目录")
    s.set_defaults(func=cmd_search)

    l = sub.add_parser("list", help="列出经验")
    l.add_argument("--tag", help="按标签筛选")
    l.add_argument("--kind", choices=KINDS, help="按类型筛选")
    l.add_argument("--root", help="项目根目录")
    l.set_defaults(func=cmd_list)

    st = sub.add_parser("stats", help="统计概览")
    st.add_argument("--root", help="项目根目录")
    st.set_defaults(func=cmd_stats)

    e = sub.add_parser("export", help="导出 markdown")
    e.add_argument("--out", help="输出文件（默认打印到屏幕）")
    e.add_argument("--root", help="项目根目录")
    e.set_defaults(func=cmd_export)

    return p


def main(argv=None):
    p = build_parser()
    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        p.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
