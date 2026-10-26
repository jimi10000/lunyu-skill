#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主动巡检 - 君子求诸己（自驱力）

不等用户下指令，自己扫一遍项目，输出「现在该做的事」。

论语出处：《论语·卫灵公》「君子求诸己，小人求诸人」——
君子遇到问题先要求自己。放到工程里：别等业务方来催，
自己先把项目体检一遍，把该做的事摆出来。

检查项（按阻断程度排序）:
  1. [阻断] 未关闭的 P0/P1 缺陷
  2. [高]   缺陷超期未处理（挂了 --due-days 天以上）
  3. [中]   今日/本周还没写日报周报
  4. [中]   有版本记录但 CHANGELOG 没跟上
  5. [低]   经验库长期没沉淀（踩过的坑没入库）
  6. [低]   工作区有未提交改动

退出码: 0=无阻断项 / 1=存在阻断项（有未关闭 P0/P1）
适合挂定时任务或 CI，作为项目健康度门禁。

用法:
  python scripts/patrol.py                 # 全量巡检
  python scripts/patrol.py --due-days 7    # 缺陷超期阈值改成 7 天
  python scripts/patrol.py --json          # 机器可读输出
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta

BLOCK_STATUSES = ("关闭",)  # 除这些外都算未闭环


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


def read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return default


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def parse_date(s):
    """容错解析日期，失败返回 None。"""
    if not s:
        return None
    s = str(s)[:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


# ---------------- 各检查项 ----------------
def check_blocking_bugs(root):
    """未关闭的 P0/P1 —— 这属于阻断项，不该带着继续开发。"""
    data = read_json(os.path.join(root, ".lunyu", "bugs.json"), {"bugs": []})
    items = data.get("bugs", [])
    open_high = [
        b for b in items
        if b.get("priority") in ("P0", "P1")
        and b.get("status") not in BLOCK_STATUSES
    ]
    if not open_high:
        return None
    lines = ["存在未关闭的 P0/P1 缺陷 %d 条，按门禁不该继续往下走：" % len(open_high)]
    for b in open_high[:10]:
        lines.append("  - %s [%s/%s] %s" % (
            b.get("id", "?"), b.get("priority", "?"),
            b.get("status", "?"), b.get("title", ""),
        ))
    lines.append("  处理: python scripts/bug_ledger.py list --status 新建")
    return ("blocking", "P0/P1 未关闭", "\n".join(lines))


def check_overdue_bugs(root, due_days):
    """挂了很久还没关的缺陷 —— 容易被忘掉。"""
    data = read_json(os.path.join(root, ".lunyu", "bugs.json"), {"bugs": []})
    items = data.get("bugs", [])
    deadline = datetime.now() - timedelta(days=due_days)
    overdue = []
    for b in items:
        if b.get("status") in BLOCK_STATUSES:
            continue
        created = parse_date(b.get("created_at") or b.get("date"))
        if created and created < deadline:
            days = (datetime.now() - created).days
            overdue.append((days, b))
    if not overdue:
        return None
    overdue.sort(key=lambda x: -x[0])
    lines = ["超过 %d 天未关闭的缺陷 %d 条（按挂起时长排序）：" % (due_days, len(overdue))]
    for days, b in overdue[:10]:
        lines.append("  - %s 已挂 %d 天 [%s] %s" % (
            b.get("id", "?"), days, b.get("priority", "?"), b.get("title", ""),
        ))
    lines.append("  处理: python scripts/bug_ledger.py show --id <编号> 重新评估优先级或关闭")
    return ("high", "缺陷超期", "\n".join(lines))


def check_missing_report(root):
    """日报/周报没写 —— 「好记性不如烂笔头」的自驱检查。"""
    rep_dir = os.path.join(root, ".lunyu", "reports")
    today = today_str()
    daily = os.path.join(rep_dir, "日报-%s.md" % today)
    iso = datetime.now().isocalendar()
    weekly = os.path.join(rep_dir, "周报-%d-%02d.md" % (iso[0], iso[1]))
    missing = []
    if not os.path.exists(daily):
        missing.append("今日日报（日报-%s.md）" % today)
    if not os.path.exists(weekly):
        missing.append("本周周报（周报-%d-%02d.md）" % (iso[0], iso[1]))
    if not missing:
        return None
    lines = ["还没写的报告：%s" % "、".join(missing)]
    lines.append("  补写: python scripts/report.py daily --project \"项目名\" --body \"今天完成...\"")
    lines.append("  也可注册自动日报: python scripts/scheduler.py install --time 18:00")
    return ("medium", "报告缺失", "\n".join(lines))


def check_changelog_behind(root):
    """有版本记录但 CHANGELOG 没跟上 —— 版本历史会断档。"""
    data = read_json(os.path.join(root, ".lunyu", "releases.json"), {"releases": []})
    items = data.get("releases", [])
    if not items:
        return None
    latest = items[-1]
    ver = str(latest.get("version", "")).lstrip("v")
    if not ver:
        return None
    cl = os.path.join(root, "CHANGELOG.md")
    if not os.path.exists(cl):
        return ("medium", "CHANGELOG 缺失",
                "已发布版本 %s，但项目根没有 CHANGELOG.md。\n"
                "  补建: 参考 Keep a Changelog 格式，或 python scripts/release_note.py tag --version %s"
                % (ver, ver))
    with open(cl, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    if ver and ver not in content:
        return ("medium", "CHANGELOG 落后",
                "最新版本 %s 未写入 CHANGELOG.md，版本历史会断档。\n"
                "  补记: python scripts/release_note.py tag --version %s --summary \"...\"" % (ver, ver))
    return None


def check_lessons_stale(root, stale_days):
    """很久没沉淀经验 —— 等于在同一个坑里反复摔。"""
    data = read_json(os.path.join(root, ".lunyu", "lessons.json"), {"lessons": []})
    items = data.get("lessons", [])
    if not items:
        return ("low", "经验库为空",
                "经验库还是空的，踩过的坑没有沉淀，下次还会再摔一次。\n"
                "  记录: python scripts/lessons.py add --scene \"场景\" --solution \"结论\" --tags \"标签\"")
    dates = [parse_date(it.get("date") or it.get("created_at")) for it in items]
    dates = [d for d in dates if d]
    if not dates:
        return None
    last = max(dates)
    gap = (datetime.now() - last).days
    if gap <= stale_days:
        return None
    return ("low", "经验久未沉淀",
            "距离上次记录经验已 %d 天（阈值 %d 天）。近期踩的坑记得入库：\n"
            "  记录: python scripts/lessons.py add --scene \"...\" --solution \"...\""
            % (gap, stale_days))


def check_uncommitted(root):
    """工作区有未提交改动 —— 长时间不提交容易丢。"""
    git_dir = os.path.join(root, ".git")
    if not os.path.isdir(git_dir):
        return None
    try:
        import subprocess
        r = subprocess.run(
            ["git", "-C", root, "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None
        lines = [l for l in r.stdout.splitlines() if l.strip()]
    except Exception:  # noqa: BLE001
        return None
    if not lines:
        return None
    return ("low", "未提交改动",
            "工作区有 %d 个未提交文件，建议及时提交或确认是否需要提交：\n"
            "  提交前先扫: python scripts/preflight.py" % len(lines))


LEVEL_ORDER = {"blocking": 0, "high": 1, "medium": 2, "low": 3}
LEVEL_LABEL = {
    "blocking": "[阻断]",
    "high": "[高]",
    "medium": "[中]",
    "low": "[低]",
}


def run_checks(root, due_days, stale_days):
    results = []
    for fn in (
        lambda: check_blocking_bugs(root),
        lambda: check_overdue_bugs(root, due_days),
        lambda: check_missing_report(root),
        lambda: check_changelog_behind(root),
        lambda: check_lessons_stale(root, stale_days),
        lambda: check_uncommitted(root),
    ):
        try:
            r = fn()
        except Exception:  # noqa: BLE001  单项检查失败不能拖垮整体巡检
            continue
        if r:
            results.append(r)
    results.sort(key=lambda x: LEVEL_ORDER.get(x[0], 9))
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description="主动巡检 - 君子求诸己（自驱力）")
    ap.add_argument("--root", help="项目根目录（默认自动向上找 .git）")
    ap.add_argument("--due-days", type=int, default=14, help="缺陷超期阈值天数（默认 14）")
    ap.add_argument("--stale-days", type=int, default=30, help="经验沉淀过期阈值天数（默认 30）")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    root = args.root or find_root()
    results = run_checks(root, args.due_days, args.stale_days)

    if args.json:
        print(json.dumps({
            "root": root,
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "blocking": any(r[0] == "blocking" for r in results),
            "items": [
                {"level": lv, "title": t, "detail": d} for lv, t, d in results
            ],
        }, ensure_ascii=False, indent=2))
        return 1 if any(r[0] == "blocking" for r in results) else 0

    print("=" * 60)
    print("巡检项目: %s" % root)
    print("巡检时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)

    if not results:
        print("\n一无所缺。项目状态健康，没有需要立刻处理的事。")
        print("（君子求诸己：没事就是最好的结果）")
        return 0

    print("\n发现 %d 项待办：\n" % len(results))
    for lv, title, detail in results:
        print("%s %s" % (LEVEL_LABEL.get(lv, "[?]"), title))
        print(detail)
        print()

    blocking = [r for r in results if r[0] == "blocking"]
    if blocking:
        print("---")
        print("存在阻断项，建议先处理再继续开发。")
        return 1
    print("---")
    print("无阻断项，上面都是提醒，按优先级自行安排。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
