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
  - 双向流通：export 出去的 markdown 可以 import 回来（按 id 去重，冲突保留最新）
  - 双层库：项目库 + 全局库(~/.lunyu)，换项目也能沉淀组织级经验
  - 过期复核：stale 列出久未复核的经验，review 标记已复核（技术会变，老结论要重验）

存储位置: <项目根>/.lunyu/lessons.json  |  全局库: ~/.lunyu/lessons.json
编号格式: L-0001 递增

用法:
  add      记一条经验（支持 --from-bug 从已关闭缺陷转化 / --global 入全局库）
  search   检索相关经验（命中会累加 hits，默认本地+全局，本地优先）
  list     列出全部（可按标签筛选）
  stats    统计概览
  export   导出 markdown 表格
  import   把 export 出去的 markdown 导回来（按 id 去重 merge）
  stale    列出超过 N 天未复核的经验
  review   标记某条经验已复核
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


def global_store_path():
    """全局经验库: 跨项目沉淀组织级经验。"""
    d = os.path.join(os.path.expanduser("~"), ".lunyu")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "lessons.json")


def target_path(args):
    """按 --global 选库: 全局库，否则项目库。"""
    if getattr(args, "use_global", False):
        return global_store_path()
    return store_path(args.root)


def load(path):
    """读经验库。文件不存在/坏 JSON/结构异常都不许崩，退化为空库。"""
    if not os.path.exists(path):
        return {"next_id": 1, "lessons": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError) as e:
        print("警告: 经验库解析失败(%s)，按空库处理: %s" % (e, path), file=sys.stderr)
        return {"next_id": 1, "lessons": []}
    if not isinstance(data, dict) or not isinstance(data.get("lessons"), list):
        print("警告: 经验库格式异常，按空库处理: %s" % path, file=sys.stderr)
        return {"next_id": 1, "lessons": []}
    data.setdefault("next_id", 1)
    return data


def save(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.now().strftime("%Y-%m-%d")


def day_of(item):
    """取经验日期(YYYY-MM-DD): 优先 date，其次 created_at 前 10 位，都没有返回空串。"""
    d = (item.get("date") or "").strip()
    if d:
        return d[:10]
    return (item.get("created_at") or "").strip()[:10]


def age_days(day):
    """距今天数。日期缺失或格式异常返回 0（脏数据不崩、也不误报为过期）。"""
    try:
        d = datetime.strptime((day or "")[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0
    return (datetime.now().date() - d).days


def id_num(lid):
    """L-0007 -> 7，解析不出返回 0。"""
    try:
        return int(str(lid).rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return 0


def next_id_for(data):
    """保证 next_id 不与现有编号冲突（导入外部 id 后尤其重要）。"""
    mx = max([id_num(it.get("id")) for it in data.get("lessons", [])] or [0])
    return max(int(data.get("next_id", 1)), mx + 1)


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


# ---------------- 缺陷 -> 经验 ----------------
def bug_ledger_path(root=None):
    """缺陷台账路径（与 bug_ledger.py 共用 .lunyu/bugs.json）。"""
    root = root or find_root()
    return os.path.join(root, ".lunyu", "bugs.json")


def fill_from_bug(args):
    """用已关闭缺陷自动填充经验字段，省掉复盘时手动重录。

    返回 (True, None) 成功；失败返回 (False, 错误信息)。
    scene=标题, problem=根因, solution=回归用例, tags 含优先级+"缺陷", kind=踩坑
    """
    path = bug_ledger_path(getattr(args, "root", None))
    if not os.path.exists(path):
        return False, "错误: 未找到缺陷台账: %s（先按 python scripts/bug_ledger.py add 登记缺陷）" % path
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError) as e:
        return False, "错误: 缺陷台账解析失败: %s (%s)" % (path, e)
    bugs = data.get("bugs", []) if isinstance(data, dict) else []

    raw = (args.from_bug or "").strip().upper()
    if raw.startswith("BUG-"):
        bid = raw
    elif raw.isdigit():  # --from-bug 1 / 0001 也认
        bid = "BUG-%04d" % int(raw)
    else:
        bid = "BUG-" + raw
    bug = None
    for b in bugs:
        if str(b.get("id", "")).upper() == bid:
            bug = b
            break
    if bug is None:
        return False, "错误: 台账中没有 %s（可用 python scripts/bug_ledger.py list 查看）" % bid
    if bug.get("status") != "关闭":
        return False, "错误: %s 尚未关闭（当前: %s），未闭环的缺陷不能转为经验" % (
            bid, bug.get("status", "未知"))

    args.scene = bug.get("title") or bid
    args.problem = bug.get("root_cause") or ""
    # 回归用例优先，其次关联 PR/备注，都没有则明确标注待补
    args.solution = (bug.get("regression") or bug.get("related_pr")
                     or "（该缺陷未记录回归用例，需补）")
    tags = [t for t in (bug.get("priority"), "缺陷") if t]
    if getattr(args, "tags", None):
        tags += [t.strip() for t in args.tags.split(",") if t.strip()]
    args.tags = ",".join(tags)
    args.kind = "踩坑"
    args.source = bid
    return True, None


# ---------------- 命令 ----------------
def cmd_add(args):
    if getattr(args, "from_bug", None):
        ok, err = fill_from_bug(args)
        if not ok:
            print(err)
            return 1
    elif not getattr(args, "scene", None) or not getattr(args, "solution", None):
        print("错误: --scene 与 --solution 必填（或用 --from-bug BUG-0001 从已关闭缺陷转化）")
        return 1

    path = target_path(args)
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
        "updated_at": now(),
        "date": today(),
        "hits": 0,
    }
    data["lessons"].append(item)
    data["next_id"] += 1
    save(path, data)
    print("已记录 %s [%s] %s" % (lid, item["kind"], item["scene"]))
    print("下次检索: python scripts/lessons.py search \"%s\"" % (item["tags"][0] if item["tags"] else item["scene"]))
    return 0


def _pools(args):
    """返回 [(标签, 路径, data, item)]，本地在前（本地优先展示）。"""
    if getattr(args, "use_global", False):
        paths = [("全局", global_store_path())]
    else:
        paths = [("本地", store_path(args.root)), ("全局", global_store_path())]
    pools = []
    for label, path in paths:
        data = load(path)
        for it in data.get("lessons", []):
            pools.append((label, path, data, it))
    return pools


def cmd_search(args):
    pools = _pools(args)
    items = [p[3] for p in pools]
    if not items:
        print("经验库为空。先记一条：python scripts/lessons.py add --scene ... --solution ...")
        return 0

    hits = search_items(items, args.query, top=args.top)
    if not hits:
        print("未检索到相关经验（关键词：%s）" % args.query)
        print("提示：这条需求本身可能就是新经验，结束后记得 add 入库。")
        return 0

    # 同分时本地优先展示（池子顺序即优先级）
    order = {id(p[3]): i for i, p in enumerate(pools)}
    hits.sort(key=lambda it: (-score(it, tokenize(args.query)), order[id(it)], it.get("id", "")))

    # 命中即加权：让高频经验自然浮到前面（各回各库，本地/全局分别落盘）
    touched = {}
    for it in hits:
        it["hits"] = it.get("hits", 0) + 1
        for _label, path, data, cand in pools:
            if cand is it:
                touched[path] = data
                break
    for path, data in touched.items():
        save(path, data)

    print("## 相关经验（%d 条，已按相关度排序）\n" % len(hits))
    for it in hits:
        scope = ""
        for label, _p, _d, cand in pools:
            if cand is it:
                scope = "（%s）" % label
                break
        tags = " ".join("#" + t for t in it.get("tags", []))
        print("### %s [%s] %s%s" % (it["id"], it.get("kind", "结论"), it.get("scene", ""), scope))
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
    print("过期未复核的用 python scripts/lessons.py stale 查看。")
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


def _seed_file():
    """种子经验库文件：references/seed-lessons.json"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "references", "seed-lessons.json")


def cmd_seed(args):
    """把内置的通用工程教训导入到当前项目，避免从空库起步。"""
    src = _seed_file()
    if not os.path.exists(src):
        print("错误: 未找到种子文件: %s" % src)
        return 1
    with open(src, "r", encoding="utf-8") as f:
        seed = json.load(f)
    incoming = seed.get("lessons", [])
    if not incoming:
        print("种子文件为空。")
        return 1

    path = store_path(args.root)
    data = load(path)
    existing = {it.get("scene") for it in data.get("lessons", [])}
    added = 0
    for item in incoming:
        if item.get("scene") in existing:
            continue  # 同场景不重复导入，可重复执行
        data["lessons"].append({
            "id": "L-%04d" % data["next_id"],
            "kind": item.get("kind", "结论"),
            "scene": item.get("scene", ""),
            "problem": item.get("problem", ""),
            "solution": item.get("solution", ""),
            "tags": item.get("tags", []),
            "source": item.get("source", ""),
            "created_at": now(),
            "date": today(),
            "hits": 0,
        })
        data["next_id"] += 1
        added += 1
    save(path, data)
    print("已导入 %d 条种子经验（跳过重复 %d 条），经验库现有 %d 条。" % (
        added, len(incoming) - added, len(data["lessons"])))
    print("查看: python scripts/lessons.py stats")
    return 0


def cmd_export(args):
    path = store_path(args.root)
    data = load(path)
    items = sorted(data.get("lessons", []), key=lambda x: (-x.get("hits", 0), x["id"]))
    # 多带一列日期，导出的 markdown 才能原样 import 回来（避免单向死产物）
    lines = ["# 经验库导出\n", "| 编号 | 类型 | 场景 | 踩坑 | 结论 | 标签 | 命中 | 日期 |",
             "|---|---|---|---|---|---|---|---|"]
    for it in items:
        cell = lambda s: (s or "").replace("|", "\\|").replace("\n", " ")
        lines.append("| %s | %s | %s | %s | %s | %s | %d | %s |" % (
            it["id"], cell(it.get("kind")), cell(it.get("scene")),
            cell(it.get("problem")), cell(it.get("solution")),
            " ".join("#" + t for t in it.get("tags", [])), it.get("hits", 0),
            day_of(it),
        ))
    out = "\n".join(lines) + "\n"
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print("已导出: %s" % args.out)
    else:
        print(out, end="")
    return 0


# ---------------- markdown 回灌 ----------------
def parse_markdown(path):
    """解析 export 出去的 markdown 表格。返回 (items, None) 或 (None, 错误信息)。

    脏行/缺列一律跳过，坏文件不崩。
    """
    if not os.path.exists(path):
        return None, "错误: 未找到文件: %s" % path
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        return None, "错误: 读取失败: %s (%s)" % (path, e)

    items = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        # 导出时把单元格里的 | 转义成 \|，这里先占位再还原，避免被切错
        cells = [c.strip().replace("\u0000", "|")
                 for c in line.strip("|").replace("\\|", "\u0000").split("|")]
        if len(cells) < 7:
            continue
        lid = cells[0]
        if lid in ("编号", "ID", "id") or set(lid) <= set("-: ") or not lid:
            continue  # 表头 / 分隔行 / 空行
        try:
            hits = int(cells[6])
        except ValueError:
            hits = 0
        items.append({
            "id": lid,
            "kind": cells[1] or "结论",
            "scene": cells[2],
            "problem": cells[3],
            "solution": cells[4],
            "tags": [t.lstrip("#") for t in cells[5].split() if t],
            "hits": hits,
            "date": cells[7][:10] if len(cells) > 7 else "",
            "source": "",
        })
    return items, None


def merge_item(old, new):
    """同 id 冲突时保留最新的那份，命中次数取大者（不丢使用热度）。"""
    merged = dict(new)
    merged["hits"] = max(int(new.get("hits", 0) or 0), int(old.get("hits", 0) or 0))
    merged.setdefault("created_at", old.get("created_at", now()))
    if not merged.get("created_at"):
        merged["created_at"] = (new.get("date") or today()) + " 00:00:00"
    merged["date"] = new.get("date") or old.get("date") or today()
    merged["updated_at"] = now()
    return merged


def cmd_import(args):
    items, err = parse_markdown(args.file)
    if err:
        print(err)
        return 1
    if not items:
        print("未从 %s 解析出经验条目（确认它是 lessons.py export 出来的表格）" % args.file)
        return 1

    path = target_path(args)
    data = load(path)
    lessons_list = data.setdefault("lessons", [])
    index = {}
    for i, it in enumerate(lessons_list):
        index.setdefault(it.get("id"), i)

    added = updated = kept = 0
    for inc in items:
        lid = inc["id"]
        if lid in index:
            i = index[lid]
            old = lessons_list[i]
            if day_of(inc) >= day_of(old):  # 导入的这份更新（同日则以导入为准）
                lessons_list[i] = merge_item(old, inc)
                updated += 1
            else:
                kept += 1  # 本地更新，保留本地
        else:
            item = dict(inc)
            item["created_at"] = (inc.get("date") or today()) + " 00:00:00"
            item["updated_at"] = now()
            lessons_list.append(item)
            index[lid] = len(lessons_list) - 1
            added += 1
    data["next_id"] = next_id_for(data)
    save(path, data)
    print("已导入 %s：新增 %d，更新 %d，保留本地较新 %d；经验库现有 %d 条。" % (
        args.file, added, updated, kept, len(lessons_list)))
    print("经验库: %s" % path)
    return 0


# ---------------- 过期复核 ----------------
def cmd_stale(args):
    path = target_path(args)
    data = load(path)
    days = args.days
    out = []
    for it in data.get("lessons", []):
        created = day_of(it)
        if not created or age_days(created) <= days:
            continue  # 还没到复核期
        reviewed = (it.get("reviewed_at") or "").strip()[:10]
        if reviewed and age_days(reviewed) <= days:
            continue  # 已复核且仍在有效期内
        out.append(it)

    if not out:
        print("无过期经验（%d 天内创建的都已复核或尚未到期）" % days)
        return 0
    out.sort(key=lambda x: (day_of(x), x.get("id", "")))
    print("## 待复核经验（%d 条，超过 %d 天）\n" % (len(out), days))
    for it in out:
        print("%s [%s] %s  创建:%s  上次复核:%s  已过 %d 天" % (
            it.get("id", ""), it.get("kind", "结论"), it.get("scene", ""),
            day_of(it) or "-", (it.get("reviewed_at") or "")[:10] or "从未",
            age_days(day_of(it))))
        print("  结论：%s" % it.get("solution", ""))
        print("  复核：python scripts/lessons.py review %s\n" % it.get("id", ""))
    print("---")
    print("技术会变，老结论要重验；复核通过的用 review 标记，确实失效的请修正或删除。")
    return 0


def cmd_review(args):
    path = target_path(args)
    data = load(path)
    target = (args.id or "").strip().upper()
    for it in data.get("lessons", []):
        if str(it.get("id", "")).upper() == target:
            it["reviewed_at"] = now()
            it["updated_at"] = now()
            save(path, data)
            print("已标记复核 %s [%s] %s（%s）" % (
                it["id"], it.get("kind", "结论"), it.get("scene", ""), it["reviewed_at"]))
            return 0
    print("未找到 %s（可用 python scripts/lessons.py list 查看编号）" % args.id)
    return 1


def build_parser():
    p = argparse.ArgumentParser(description="经验库 - 告诸往而知来者（自学习）")
    sub = p.add_subparsers(dest="cmd")

    a = sub.add_parser("add", help="记一条经验")
    # scene/solution 交给 cmd_add 校验：--from-bug 时无需手填
    a.add_argument("--scene", help="什么场景（如：车机静态广播）")
    a.add_argument("--solution", help="结论/正确做法")
    a.add_argument("--problem", help="踩过的坑（错在哪）")
    a.add_argument("--tags", help="标签，逗号分隔（如：android,车机,广播）")
    a.add_argument("--kind", choices=KINDS, default="结论", help="类型")
    a.add_argument("--source", help="来源（如：哪吒车机实测）")
    a.add_argument("--from-bug", help="从已关闭缺陷转化（如 BUG-0001），省掉手动重录")
    a.add_argument("--global", dest="use_global", action="store_true",
                   help="记入全局库 ~/.lunyu/lessons.json（跨项目复用）")
    a.add_argument("--root", help="项目根目录")
    a.set_defaults(func=cmd_add)

    s = sub.add_parser("search", help="检索相关经验（命中累加 hits）")
    s.add_argument("query", help="关键词/场景描述")
    s.add_argument("--top", type=int, default=5, help="返回条数")
    s.add_argument("--global", dest="use_global", action="store_true",
                   help="只查全局库（默认本地+全局，本地优先）")
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

    sd = sub.add_parser("seed", help="导入内置种子经验（避免从空库起步）")
    sd.add_argument("--root", help="项目根目录")
    sd.set_defaults(func=cmd_seed)

    e = sub.add_parser("export", help="导出 markdown")
    e.add_argument("--out", help="输出文件（默认打印到屏幕）")
    e.add_argument("--root", help="项目根目录")
    e.set_defaults(func=cmd_export)

    im = sub.add_parser("import", help="把 export 出去的 markdown 导回来（按 id 去重）")
    im.add_argument("--file", required=True, help="经验库 markdown 文件")
    im.add_argument("--global", dest="use_global", action="store_true", help="导入到全局库")
    im.add_argument("--root", help="项目根目录")
    im.set_defaults(func=cmd_import)

    sl = sub.add_parser("stale", help="列出超过 N 天未复核的经验")
    sl.add_argument("--days", type=int, default=180, help="过期天数（默认 180）")
    sl.add_argument("--global", dest="use_global", action="store_true", help="查全局库")
    sl.add_argument("--root", help="项目根目录")
    sl.set_defaults(func=cmd_stale)

    rv = sub.add_parser("review", help="标记某条经验已复核")
    rv.add_argument("id", help="经验编号，如 L-0001")
    rv.add_argument("--global", dest="use_global", action="store_true", help="标记全局库")
    rv.add_argument("--root", help="项目根目录")
    rv.set_defaults(func=cmd_review)

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
