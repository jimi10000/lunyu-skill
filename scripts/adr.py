#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""架构决策记录（ADR）- 温故而知新：决策也要可追溯

方案文档里的「设计取舍」会随版本淹没，后人只看到结果、看不到当年否决 B 方案的
理由，于是同一个辩论反复重开。ADR 把「为什么这么定、为什么不那么定」单独存一份：

  new 记录取舍 -> list/show 回看 -> supersede 演进留痕 -> link 挂到版本

存储位置:
  正文  <项目根>/.lunyu/decisions/0001-<slug>.md
  索引  <项目根>/.lunyu/decisions.json（脚本维护，坏了能自愈）

用法:
  new       新建一条架构决策
  list      列出全部 ADR
  show      查看某条 ADR 正文
  supersede 用新 ADR 取代旧 ADR（旧记录留痕，不删）
  link      把 ADR 关联到发布版本
"""
import argparse
import json
import os
import sys
from datetime import datetime

STATUSES = ("已接受", "已弃用", "已被取代", "待定")
EMPTY = "（未记录）"


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
    """索引文件路径, 同时保证 .lunyu/decisions/ 存在"""
    root = root or find_root()
    d = os.path.join(root, ".lunyu")
    os.makedirs(os.path.join(d, "decisions"), exist_ok=True)
    return os.path.join(d, "decisions.json")


def decisions_dir(root=None):
    root = root or find_root()
    d = os.path.join(root, ".lunyu", "decisions")
    os.makedirs(d, exist_ok=True)
    return d


def load(path):
    """读索引; 文件损坏/结构不合法时从 .lunyu/decisions/*.md 重建, 不崩溃"""
    if not os.path.exists(path):
        return {"next_id": 1, "decisions": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return rebuild(path)
    if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
        return rebuild(path)
    data["next_id"] = int(data.get("next_id") or 1)
    for it in data["decisions"]:
        if not isinstance(it, dict):
            return rebuild(path)
    return data


def rebuild(path):
    """索引不可信时扫正文目录重建: 编号/标题/状态/文件都从 .md 里取"""
    print("警告: %s 不可用, 已自动重建索引" % os.path.basename(path))
    d = os.path.join(os.path.dirname(path), "decisions")
    items = []
    if os.path.isdir(d):
        for name in sorted(os.listdir(d)):
            if not name.endswith(".md"):
                continue
            head = name[:-3]
            adr_id = head.split("-", 1)[0]
            title, status = head, "待定"
            try:
                with open(os.path.join(d, name), "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("# "):
                            title = line[2:].split(" ", 1)[-1] or head
                        if line.startswith("- 状态："):
                            status = line.split("：", 1)[1].strip()
            except OSError:
                pass
            items.append({
                "id": adr_id,
                "title": title,
                "slug": head.split("-", 1)[-1] if "-" in head else "",
                "status": status,
                "date": "",
                "context": "",
                "decision": "",
                "alternatives": [],
                "consequences": "",
                "positive": "",
                "negative": "",
                "related_versions": [],
                "superseded_by": "",
                "supersedes": [],
                "file": name,
                "created_at": "",
                "updated_at": "",
            })
    next_id = 1
    for it in items:
        digits = "".join(ch for ch in str(it["id"]) if ch.isdigit())
        if digits:
            next_id = max(next_id, int(digits) + 1)
    return {"next_id": next_id, "decisions": items}


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.now().strftime("%Y-%m-%d")


def norm_id(raw):
    """归一化编号: 1 / 0001 / ADR-0001 / #0001 都认"""
    s = str(raw or "").strip().upper()
    if s.startswith("ADR"):
        s = s[3:]
    digits = "".join(ch for ch in s.lstrip("#-") if ch.isdigit())
    if not digits:
        return None
    return "%04d" % int(digits)


def slugify(title):
    """中文/英数保留, 其余转连字符; 不做拼音转换, 避免引入依赖"""
    out = []
    for ch in str(title or "").strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif ch in " \t_/\\.":
            out.append("-")
    s = "".join(out)
    while "--" in s:
        s = s.replace("--", "-")
    s = s.strip("-")
    return s[:40] or "adr"


def parse_alternative(text):
    """备选方案写法: '名称|否决理由' 或 '名称:否决理由'; 只给名称也收"""
    for sep in ("|", "：", ":"):
        if sep in text:
            name, reason = text.split(sep, 1)
            return {"name": name.strip(), "reason": reason.strip()}
    return {"name": text.strip(), "reason": ""}


def _body(text):
    return (text or "").strip() or EMPTY


def render_md(item):
    lines = ["# %s %s" % (item["id"], item["title"]), ""]
    lines.append("- 状态：%s" % item["status"])
    lines.append("- 日期：%s" % (item.get("date") or EMPTY))
    if item.get("related_versions"):
        lines.append("- 关联版本：%s" % "、".join(item["related_versions"]))
    if item.get("superseded_by"):
        lines.append("- 已被取代：ADR %s" % item["superseded_by"])
    if item.get("supersedes"):
        lines.append("- 取代了：ADR %s" % "、".join(item["supersedes"]))
    lines.append("")

    lines.append("## 背景")
    lines.append(_body(item.get("context")))
    lines.append("")

    lines.append("## 决定")
    lines.append(_body(item.get("decision")))
    lines.append("")

    lines.append("## 备选方案（及否决理由）")
    alts = item.get("alternatives") or []
    if alts:
        for i, alt in enumerate(alts, 1):
            lines.append("%d. %s" % (i, alt.get("name", "")))
            if alt.get("reason"):
                lines.append("   - 否决理由：%s" % alt["reason"])
            else:
                lines.append("   - 否决理由：%s" % EMPTY)
    else:
        lines.append(EMPTY)
    lines.append("")

    lines.append("## 影响")
    cons = []
    if item.get("positive"):
        cons.append("- 正面：%s" % item["positive"])
    if item.get("negative"):
        cons.append("- 负面：%s" % item["negative"])
    if item.get("consequences"):
        cons.append("- 综合：%s" % item["consequences"])
    lines.extend(cons or [EMPTY])
    lines.append("")

    lines.append("## 关联版本")
    if item.get("related_versions"):
        for v in item["related_versions"]:
            lines.append("- %s" % v)
    else:
        lines.append(EMPTY)
    lines.append("")

    return "\n".join(lines)


def write_md(root, item):
    """按当前索引内容重写正文, 保证 .md 与索引一致"""
    target = os.path.join(decisions_dir(root), item["file"])
    with open(target, "w", encoding="utf-8") as f:
        f.write(render_md(item))
    return target


def find_item(data, raw_id):
    adr_id = norm_id(raw_id)
    for it in data["decisions"]:
        if norm_id(it.get("id")) == adr_id:
            return it
    return None


def cmd_new(args):
    path = store_path(args.root)
    data = load(path)
    adr_id = "%04d" % data["next_id"]
    slug = slugify(args.title)
    item = {
        "id": adr_id,
        "title": args.title,
        "slug": slug,
        "status": args.status,
        "date": today(),
        "context": args.context or "",
        "decision": args.decision or "",
        "alternatives": [parse_alternative(a) for a in (args.alternatives or [])],
        "consequences": args.consequences or "",
        "positive": args.positive or "",
        "negative": args.negative or "",
        "related_versions": [args.related_version] if args.related_version else [],
        "superseded_by": "",
        "supersedes": [],
        "file": "%s-%s.md" % (adr_id, slug),
        "created_at": now(),
        "updated_at": now(),
    }
    data["decisions"].append(item)
    data["next_id"] += 1
    save(path, data)
    target = write_md(args.root, item)
    print("已记录 ADR %s [%s] %s" % (adr_id, item["status"], item["title"]))
    print("正文: %s" % target)
    return 0


def cmd_list(args):
    path = store_path(args.root)
    data = load(path)
    items = data["decisions"]
    if args.status:
        items = [it for it in items if it.get("status") == args.status]
    if not items:
        print("暂无架构决策记录")
        return 0
    print("%-8s%-10s%-14s%s" % ("编号", "状态", "日期", "标题"))
    print("-" * 70)
    for it in items:
        print("%-8s%-10s%-14s%s" % (
            it.get("id", ""), it.get("status", ""), it.get("date", ""), it.get("title", "")))
    print("\n共 %d 条" % len(items))
    return 0


def cmd_show(args):
    path = store_path(args.root)
    data = load(path)
    item = find_item(data, args.id)
    if item is None:
        print("未找到 ADR %s" % args.id)
        sys.exit(1)
    target = os.path.join(decisions_dir(args.root), item["file"])
    if os.path.exists(target):
        with open(target, "r", encoding="utf-8") as f:
            print(f.read(), end="")
    else:
        print(render_md(item))
    return 0


def cmd_supersede(args):
    path = store_path(args.root)
    data = load(path)
    old = find_item(data, args.id)
    new = find_item(data, args.by)
    if old is None:
        print("未找到 ADR %s" % args.id)
        sys.exit(1)
    if new is None:
        print("未找到 ADR %s" % args.by)
        sys.exit(1)
    if norm_id(old["id"]) == norm_id(new["id"]):
        print("不能用自己取代自己")
        sys.exit(1)

    old["status"] = "已被取代"
    old["superseded_by"] = new["id"]
    old["updated_at"] = now()
    olds = [x for x in new.get("supersedes", []) if x != old["id"]]
    olds.append(old["id"])
    new["supersedes"] = olds
    new["updated_at"] = now()
    save(path, data)
    write_md(args.root, old)
    write_md(args.root, new)
    print("ADR %s 已被 %s 取代（旧记录保留可追溯）" % (old["id"], new["id"]))
    return 0


def cmd_link(args):
    path = store_path(args.root)
    data = load(path)
    item = find_item(data, args.id)
    if item is None:
        print("未找到 ADR %s" % args.id)
        sys.exit(1)
    versions = item.get("related_versions") or []
    if args.version not in versions:
        versions.append(args.version)
    item["related_versions"] = versions
    item["updated_at"] = now()
    save(path, data)
    write_md(args.root, item)
    print("ADR %s 已关联版本 %s" % (item["id"], args.version))
    return 0


def build_parser():
    p = argparse.ArgumentParser(description="架构决策记录（ADR）- 决策可追溯")
    sub = p.add_subparsers(dest="cmd")

    n = sub.add_parser("new", help="新建一条架构决策")
    n.add_argument("--title", required=True, help="决策标题")
    n.add_argument("--context", required=True, help="背景：当时面对什么问题")
    n.add_argument("--decision", required=True, help="决定：最终选了什么")
    n.add_argument("--alternatives", nargs="+", default=[],
                   help='备选方案，写法："名称|否决理由"')
    n.add_argument("--consequences", required=True, help="影响（综合说明）")
    n.add_argument("--positive", help="正面影响")
    n.add_argument("--negative", help="负面影响")
    n.add_argument("--status", choices=STATUSES, default="已接受")
    n.add_argument("--related-version", help="关联版本，如 v1.2.0")
    n.add_argument("--root", help="项目根目录")
    n.set_defaults(func=cmd_new)

    l = sub.add_parser("list", help="列出 ADR")
    l.add_argument("--status", choices=STATUSES, help="按状态筛选")
    l.add_argument("--root", help="项目根目录")
    l.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="查看 ADR 正文")
    s.add_argument("id")
    s.add_argument("--root", help="项目根目录")
    s.set_defaults(func=cmd_show)

    su = sub.add_parser("supersede", help="用新 ADR 取代旧 ADR")
    su.add_argument("id", help="被取代的旧编号")
    su.add_argument("--by", required=True, help="取代它的新编号")
    su.add_argument("--root", help="项目根目录")
    su.set_defaults(func=cmd_supersede)

    lk = sub.add_parser("link", help="关联 ADR 与发布版本")
    lk.add_argument("--id", required=True, help="ADR 编号")
    lk.add_argument("--version", required=True, help="版本号，如 v1.2.0")
    lk.add_argument("--root", help="项目根目录")
    lk.set_defaults(func=cmd_link)

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
