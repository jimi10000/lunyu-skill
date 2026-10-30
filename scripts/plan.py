#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实施计划 - 欲速则不达

论语出处：《论语·子路》「欲速则不达，见小利则大事不成」——
图快反而到不了。放到工程里：拿到需求一把梭写到底，是最常见的翻车姿势。
正确做法是先拆成小任务，每个任务有明确的「怎么算做完」，做完一个打一个勾。

核心价值不在「列清单」，在**每个任务必须写验收点**。
没写验收点的任务等于没拆——你永远不知道它到底做完没有。

命令:
    new --title "..." --acceptance "..."     新增任务（验收点必填）
    new --from 技术方案.md                    从 md 里的 - [ ] 批量导入
    list                                    列出全部任务与进度
    start <id>                              标记开始
    done <id> [--evidence "..."]            标记完成（--strict 下必须带证据）
    show <id>                               查看单个任务
    reset <id>                              退回未完成
    clear                                   清空计划（会确认）
    gate                                    检查是否全部完成，未完成返回 1（挂 CI）

退出码:
    0 = 正常
    1 = gate 有未完成 / 操作失败
    2 = 参数错误
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

PLAN_FILE = "plan.json"
STATUS_TODO, STATUS_DOING, STATUS_DONE = "todo", "doing", "done"
STATUS_CN = {STATUS_TODO: "待做", STATUS_DOING: "进行中", STATUS_DONE: "已完成"}
TODO_RE = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*(.+)$")


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
    return d, os.path.join(d, PLAN_FILE)


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


def load(root):
    d, path = store_path(root)
    data = read_json(path, None) or {}
    if not isinstance(data.get("tasks"), list):
        data["tasks"] = []
    return data, path


def next_id(tasks):
    return (max((t.get("id") or 0) for t in tasks) + 1) if tasks else 1


def find_task(tasks, tid):
    for t in tasks:
        if t.get("id") == tid:
            return t
    return None


def cmd_new(args):
    root = os.path.abspath(args.root or find_root())
    data, path = load(root)
    tasks = data["tasks"]

    if args.from_file:
        p = args.from_file if os.path.isabs(args.from_file) else os.path.join(root, args.from_file)
        if not os.path.exists(p):
            print("错误: 文件不存在: %s" % args.from_file, file=sys.stderr)
            return 1
        try:
            with open(p, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError as e:
            print("错误: 读不动 %s (%s)" % (p, e), file=sys.stderr)
            return 1
        added = 0
        for line in lines:
            m = TODO_RE.match(line)
            if not m:
                continue
            title = m.group(2).strip()
            if not title:
                continue
            tasks.append({
                "id": next_id(tasks),
                "title": title,
                "acceptance": "",
                "status": STATUS_DONE if m.group(1).lower() == "x" else STATUS_TODO,
                "evidence": "",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "done_at": "",
            })
            added += 1
        if not added:
            print("警告: 文件里没找到 `- [ ]` 形式的条目", file=sys.stderr)
            return 1
        write_json(path, data)
        print("已从 %s 导入 %d 个任务" % (os.path.basename(p), added))
        print("警告: 导入的任务没有验收点。请逐个补 `python scripts/plan.py set-acceptance <id> --acceptance \"...\"`",
              file=sys.stderr)
        return 0

    if not args.title:
        print("错误: --title 必填（或给 --from 批量导入）", file=sys.stderr)
        return 2
    if not args.acceptance:
        print("错误: --acceptance 必填。没写验收点的任务等于没拆——"
              "你永远不知道它做完没有。", file=sys.stderr)
        return 2
    task = {
        "id": next_id(tasks),
        "title": args.title,
        "acceptance": args.acceptance,
        "status": STATUS_TODO,
        "evidence": "",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "done_at": "",
    }
    tasks.append(task)
    data["tasks"] = tasks
    if not write_json(path, data):
        print("错误: 写入失败", file=sys.stderr)
        return 1
    print("已新增任务 #%d: %s" % (task["id"], task["title"]))
    print("  验收点: %s" % task["acceptance"])
    return 0


def cmd_list(args):
    root = os.path.abspath(args.root or find_root())
    data, path = load(root)
    tasks = data["tasks"]
    if not tasks:
        print("还没有任务。新增: python scripts/plan.py new --title \"...\" --acceptance \"...\"")
        return 0

    if args.json:
        print(json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2))
        return 0

    done = sum(1 for t in tasks if t.get("status") == STATUS_DONE)
    print("=" * 60)
    print("实施计划: %s" % root)
    print("进度: %d/%d" % (done, len(tasks)))
    print("=" * 60)
    for t in tasks:
        st = t.get("status", STATUS_TODO)
        mark = {STATUS_DONE: "[√]", STATUS_DOING: "[→]", STATUS_TODO: "[ ]"}.get(st, "[ ]")
        print("%s #%-3d %s" % (mark, t.get("id"), t.get("title", "")))
        acc = (t.get("acceptance") or "").strip()
        print("      验收: %s" % (acc if acc else "（未写 —— 这个任务算不算做完没法判断）"))
        if st == STATUS_DONE and t.get("evidence"):
            print("      证据: %s" % t["evidence"])
    print("")
    no_acc = [t.get("id") for t in tasks if not (t.get("acceptance") or "").strip()]
    if no_acc:
        print("警告: 任务 %s 没写验收点。" % "、".join("#%s" % i for i in no_acc))
    return 0


def cmd_start(args):
    root = os.path.abspath(args.root or find_root())
    data, path = load(root)
    t = find_task(data["tasks"], args.id)
    if not t:
        print("错误: 没有任务 #%s" % args.id, file=sys.stderr)
        return 1
    t["status"] = STATUS_DOING
    write_json(path, data)
    print("#%d 开始: %s" % (t["id"], t["title"]))
    return 0


def cmd_done(args):
    root = os.path.abspath(args.root or find_root())
    data, path = load(root)
    t = find_task(data["tasks"], args.id)
    if not t:
        print("错误: 没有任务 #%s" % args.id, file=sys.stderr)
        return 1
    if args.strict and not args.evidence:
        print("错误: --strict 模式下必须给 --evidence。\n"
              "「做完了」要有证据：测试结果、命令输出、截图路径都行。",
              file=sys.stderr)
        return 2
    if not (t.get("acceptance") or "").strip():
        print("警告: 这个任务没写验收点，你凭什么判断它做完了？", file=sys.stderr)
    t["status"] = STATUS_DONE
    t["evidence"] = args.evidence or ""
    t["done_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_json(path, data)
    print("#%d 完成: %s" % (t["id"], t["title"]))
    if t["evidence"]:
        print("  证据: %s" % t["evidence"])
    return 0


def cmd_show(args):
    root = os.path.abspath(args.root or find_root())
    data, path = load(root)
    t = find_task(data["tasks"], args.id)
    if not t:
        print("错误: 没有任务 #%s" % args.id, file=sys.stderr)
        return 1
    print(json.dumps(t, ensure_ascii=False, indent=2))
    return 0


def cmd_reset(args):
    root = os.path.abspath(args.root or find_root())
    data, path = load(root)
    t = find_task(data["tasks"], args.id)
    if not t:
        print("错误: 没有任务 #%s" % args.id, file=sys.stderr)
        return 1
    t["status"] = STATUS_TODO
    t["done_at"] = ""
    write_json(path, data)
    print("#%d 已退回待做" % t["id"])
    return 0


def cmd_set_acceptance(args):
    root = os.path.abspath(args.root or find_root())
    data, path = load(root)
    t = find_task(data["tasks"], args.id)
    if not t:
        print("错误: 没有任务 #%s" % args.id, file=sys.stderr)
        return 1
    if not args.acceptance:
        print("错误: --acceptance 必填", file=sys.stderr)
        return 2
    t["acceptance"] = args.acceptance
    write_json(path, data)
    print("#%d 验收点已更新" % t["id"])
    return 0


def cmd_clear(args):
    root = os.path.abspath(args.root or find_root())
    d, path = store_path(root)
    data = load(root)[0]
    if not data["tasks"]:
        print("计划本来就是空的")
        return 0
    if not args.yes:
        print("将清空 %d 个任务。确认请加 --yes" % len(data["tasks"]))
        return 1
    write_json(path, {"tasks": []})
    print("已清空计划")
    return 0


def cmd_gate(args):
    """全部完成才放行 —— 挂 CI 或交付前用。"""
    root = os.path.abspath(args.root or find_root())
    data, path = load(root)
    tasks = data["tasks"]
    if not tasks:
        print("没有任务，放行")
        return 0
    undone = [t for t in tasks if t.get("status") != STATUS_DONE]
    no_acc = [t for t in tasks if not (t.get("acceptance") or "").strip()]
    if not undone and not no_acc:
        print("全部 %d 个任务完成，且都有验收点。放行。" % len(tasks))
        return 0
    if undone:
        print("阻断: 还有 %d 个任务没完成: %s"
              % (len(undone), "、".join("#%s %s" % (t["id"], t["title"]) for t in undone)))
    if no_acc:
        print("阻断: 有 %d 个任务没写验收点: %s"
              % (len(no_acc), "、".join("#%s" % t["id"] for t in no_acc)))
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="实施计划 - 欲速则不达（拆小步，每步有验收点）")
    ap.add_argument("--root", help="项目根目录（默认向上找 .git）")
    sub = ap.add_subparsers(dest="cmd")

    n = sub.add_parser("new", help="新增任务（验收点必填）")
    n.add_argument("--title", help="任务标题")
    n.add_argument("--acceptance", help="验收点：怎么算做完了（必填）")
    n.add_argument("--from", dest="from_file", help="从 md 的 - [ ] 批量导入")
    n.set_defaults(func=cmd_new)

    l = sub.add_parser("list", help="列出任务与进度")
    l.add_argument("--json", action="store_true", help="机器可读")
    l.set_defaults(func=cmd_list)

    st = sub.add_parser("start", help="标记开始")
    st.add_argument("id", type=int)
    st.set_defaults(func=cmd_start)

    d = sub.add_parser("done", help="标记完成")
    d.add_argument("id", type=int)
    d.add_argument("--evidence", help="证据：测试结果 / 命令输出 / 截图路径")
    d.add_argument("--strict", action="store_true", help="强制要求证据")
    d.set_defaults(func=cmd_done)

    s = sub.add_parser("show", help="查看任务")
    s.add_argument("id", type=int)
    s.set_defaults(func=cmd_show)

    r = sub.add_parser("reset", help="退回未完成")
    r.add_argument("id", type=int)
    r.set_defaults(func=cmd_reset)

    sa = sub.add_parser("set-acceptance", help="补写验收点")
    sa.add_argument("id", type=int)
    sa.add_argument("--acceptance", required=True)
    sa.set_defaults(func=cmd_set_acceptance)

    c = sub.add_parser("clear", help="清空计划")
    c.add_argument("--yes", action="store_true", help="确认清空")
    c.set_defaults(func=cmd_clear)

    g = sub.add_parser("gate", help="全部完成才放行（挂 CI）")
    g.set_defaults(func=cmd_gate)

    args = ap.parse_args(argv)
    if not getattr(args, "func", None):
        ap.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
