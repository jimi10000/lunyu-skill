#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report.py — 项目总结 / 日报 / 周报 自动生成

「好记性不如烂笔头」：每次写完一个项目要有总结，每天要有日报，每周要有周报。
本脚本自动汇总 .lunyu/ 下的缺陷台账、版本存档、CHANGELOG，生成 Markdown 报告，
并追加到项目根目录 .lunyu/reports/ 下，形成可追溯的「烂笔头」。

用法:
    # 项目总结（跑完一个项目/大版本后写）
    python scripts/report.py summary --project "项目名" [--author 你]

    # 日报（默认今天）
    python scripts/report.py daily [--date 2026-10-26] [--project "项目名"] [--author 你]

    # 周报（默认本周）
    python scripts/report.py weekly [--date 2026-10-26] [--project "项目名"] [--author 你]

    # 列出已生成的报告
    python scripts/report.py list

    # 自定义正文追加（命令行传多段，或从文件读）
    python scripts/report.py daily --body "今天完成了XX" --body "修了YY bug"

数据来源（自动读取，缺省则留空不报错）:
    .lunyu/bugs.json       缺陷台账（P0-P3、状态、今日/本周关闭数）
    .lunyu/releases.json   版本存档（今日/本周 tag）
    .lunyu/CHANGELOG.md    变更日志（今日/本周条目）

输出:
    .lunyu/reports/项目总结-YYYYMMDD.md
    .lunyu/reports/日报-YYYY-MM-DD.md
    .lunyu/reports/周报-YYYY-WW.md
"""
import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta

LUNYU_DIR = ".lunyu"
REPORTS_DIR = os.path.join(LUNYU_DIR, "reports")
BUGS_FILE = os.path.join(LUNYU_DIR, "bugs.json")
RELEASES_FILE = os.path.join(LUNYU_DIR, "releases.json")
CHANGELOG_FILE = os.path.join(LUNYU_DIR, "CHANGELOG.md")


# ---------- 数据读取 ----------
def load_json(path):
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_changelog():
    if not os.path.isfile(CHANGELOG_FILE):
        return []
    try:
        with open(CHANGELOG_FILE, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return []
    # 解析 ## [x.y.z] - YYYY-MM-DD 标题
    entries = []
    for m in re.finditer(r"^##\s+\[([^\]]+)\]\s*-\s*(\d{4}-\d{2}-\d{2})", text, re.MULTILINE):
        entries.append({"version": m.group(1), "date": m.group(2)})
    return entries


def filter_by_date(items, date_str):
    """按日期过滤 items（item 含 date 字段）。返回 (今日, 本周) 两组。"""
    if not items:
        return [], []
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return [], []
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    today, week = [], []
    for it in items:
        try:
            it_date = datetime.strptime(it.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if it_date == d:
            today.append(it)
        if monday <= it_date <= sunday:
            week.append(it)
    return today, week


def summarize_bugs(bugs, date_str):
    """汇总缺陷台账：今日/本周关闭数、未关闭 P0/P1、按优先级分布。"""
    if not bugs:
        return None
    # bugs.json 可能是 {"bugs": [...]} 或 list
    items = bugs if isinstance(bugs, list) else bugs.get("bugs", [])
    if not items:
        return None
    today_closed, week_closed = 0, 0
    open_p0p1 = []
    dist = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        monday = d - timedelta(days=d.weekday())
        sunday = monday + timedelta(days=6)
    except ValueError:
        d, monday, sunday = None, None, None

    for it in items:
        prio = it.get("priority", "P3")
        dist[prio] = dist.get(prio, 0) + 1
        status = it.get("status", "")
        if status in ("关闭", "closed", "done"):
            # 优先用关闭时记录的时间，其次更新/创建时间
            closed_date = it.get("closed_at", it.get("updated_at", ""))
            try:
                cd = datetime.strptime(str(closed_date)[:10], "%Y-%m-%d").date()
                if d and cd == d:
                    today_closed += 1
                if monday and monday <= cd <= sunday:
                    week_closed += 1
            except ValueError:
                pass
        elif prio in ("P0", "P1") and status not in ("关闭", "closed", "done"):
            open_p0p1.append(f"{prio} {it.get('title', '?')}")

    return {
        "total": len(items),
        "open_p0p1": open_p0p1,
        "today_closed": today_closed,
        "week_closed": week_closed,
        "dist": dist,
    }


def summarize_releases(releases, date_str):
    """汇总版本存档：今日/本周 tag。"""
    if not releases:
        return None
    items = releases if isinstance(releases, list) else releases.get("releases", [])
    if not items:
        return None
    # release 记录用 created_at，统一映射成 filter_by_date 认识的 date 字段
    norm = []
    for it in items:
        entry = dict(it)
        entry.setdefault("date", str(entry.get("created_at", ""))[:10])
        norm.append(entry)
    today, week = filter_by_date(norm, date_str)
    return {
        "today_tags": [it.get("version", "?") for it in today],
        "week_tags": [it.get("version", "?") for it in week],
    }


# ---------- 报告生成 ----------
def esc(text):
    return str(text).replace("\n", " ").strip()


def gen_summary(project, author, body_blocks):
    today = date.today().isoformat()
    bugs = load_json(BUGS_FILE)
    rel = load_json(RELEASES_FILE)
    cl = load_changelog()

    lines = []
    lines.append(f"# 项目总结：{project}")
    lines.append("")
    lines.append(f"- **项目**：{project}")
    lines.append(f"- **总结日期**：{today}")
    lines.append(f"- **作者**：{author or '（未填写）'}")
    lines.append("")
    lines.append("## 一、交付概览")
    lines.append("")
    if rel:
        tags = [it.get("version", "?") for it in (rel if isinstance(rel, list) else rel.get("releases", []))]
        lines.append(f"- 版本存档：{len(tags)} 个版本（{', '.join(tags[-10:])}）")
    else:
        lines.append("- 版本存档：无（未使用 release_note.py 打 tag）")
    if cl:
        lines.append(f"- CHANGELOG：{len(cl)} 条版本记录")
    else:
        lines.append("- CHANGELOG：无")
    lines.append("")

    lines.append("## 二、缺陷总结")
    lines.append("")
    if bugs:
        b = summarize_bugs(bugs, today)
        if b:
            lines.append(f"- 缺陷总数：{b['total']}")
            lines.append(f"- 分布：P0={b['dist'].get('P0',0)} / P1={b['dist'].get('P1',0)} / P2={b['dist'].get('P2',0)} / P3={b['dist'].get('P3',0)}")
            if b["open_p0p1"]:
                lines.append("- 未关闭 P0/P1：")
                for x in b["open_p0p1"]:
                    lines.append(f"  - {x}")
            else:
                lines.append("- 未关闭 P0/P1：无")
        lines.append("")
    else:
        lines.append("- 缺陷台账：无（未使用 bug_ledger.py）")
        lines.append("")

    lines.append("## 三、主要成果")
    lines.append("")
    if body_blocks:
        for b in body_blocks:
            lines.append(f"- {esc(b)}")
    else:
        lines.append("（待补充：本项目的核心成果、技术亮点）")
    lines.append("")

    lines.append("## 四、经验与教训（吾日三省）")
    lines.append("")
    lines.append("### ✅ 收获")
    lines.append("- （待补充）")
    lines.append("")
    lines.append("### ⚠️ 失误与改进")
    lines.append("- （待补充）")
    lines.append("")
    lines.append("### 🐛 缺陷根因")
    lines.append("- （待补充）")
    lines.append("")
    lines.append("## 五、遗留事项")
    lines.append("")
    if bugs:
        b = summarize_bugs(bugs, today)
        if b and b["open_p0p1"]:
            for x in b["open_p0p1"]:
                lines.append(f"- [ ] {x}")
        else:
            lines.append("- 无未关闭 P0/P1")
    else:
        lines.append("- （待补充）")
    lines.append("")

    return "\n".join(lines), f"项目总结-{today.replace('-', '')}.md"


def gen_daily(project, author, body_blocks, date_str):
    bugs = load_json(BUGS_FILE)
    rel = load_json(RELEASES_FILE)
    cl = load_changelog()
    today, _ = filter_by_date(cl, date_str)
    bug_sum = summarize_bugs(bugs, date_str)

    lines = []
    lines.append(f"# 日报：{date_str}")
    lines.append("")
    lines.append(f"- **项目**：{project or '（未指定）'}")
    lines.append(f"- **日期**：{date_str}")
    lines.append(f"- **作者**：{author or '（未填写）'}")
    lines.append("")
    lines.append("## 今日完成")
    lines.append("")
    if body_blocks:
        for b in body_blocks:
            lines.append(f"- {esc(b)}")
    else:
        lines.append("- （待补充）")
    lines.append("")
    lines.append("## 今日数据")
    lines.append("")
    if bug_sum:
        lines.append(f"- 缺陷：今日关闭 {bug_sum['today_closed']} 个，未关闭 P0/P1：{len(bug_sum['open_p0p1'])} 个")
    else:
        lines.append("- 缺陷台账：无")
    if rel:
        rs = summarize_releases(rel, date_str)
        if rs and rs["today_tags"]:
            lines.append(f"- 今日发版：{', '.join(rs['today_tags'])}")
    if today:
        lines.append(f"- 今日 CHANGELOG：{', '.join(e['version'] for e in today)}")
    lines.append("")
    lines.append("## 明日计划")
    lines.append("")
    lines.append("- （待补充）")
    lines.append("")
    lines.append("## 风险与阻塞")
    lines.append("")
    if bug_sum and bug_sum["open_p0p1"]:
        for x in bug_sum["open_p0p1"]:
            lines.append(f"- [ ] {x}")
    else:
        lines.append("- 无")
    lines.append("")

    return "\n".join(lines), f"日报-{date_str}.md"


def gen_weekly(project, author, body_blocks, date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        d = date.today()
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    week_label = f"{monday.isoformat()} ~ {sunday.isoformat()}"

    bugs = load_json(BUGS_FILE)
    rel = load_json(RELEASES_FILE)
    cl = load_changelog()
    _, week_changelog = filter_by_date(cl, d.isoformat())
    bug_sum = summarize_bugs(bugs, d.isoformat())

    lines = []
    lines.append(f"# 周报：{week_label}")
    lines.append("")
    lines.append(f"- **项目**：{project or '（未指定）'}")
    lines.append(f"- **周期**：{week_label}")
    lines.append(f"- **作者**：{author or '（未填写）'}")
    lines.append("")
    lines.append("## 本周完成")
    lines.append("")
    if body_blocks:
        for b in body_blocks:
            lines.append(f"- {esc(b)}")
    else:
        lines.append("- （待补充）")
    lines.append("")
    lines.append("## 本周数据")
    lines.append("")
    if bug_sum:
        lines.append(f"- 缺陷：本周关闭 {bug_sum['week_closed']} 个，未关闭 P0/P1：{len(bug_sum['open_p0p1'])} 个")
    else:
        lines.append("- 缺陷台账：无")
    if rel:
        rs = summarize_releases(rel, d.isoformat())
        if rs and rs["week_tags"]:
            lines.append(f"- 本周发版：{', '.join(rs['week_tags'])}")
    if week_changelog:
        lines.append(f"- 本周 CHANGELOG：{', '.join(e['version'] for e in week_changelog)}")
    lines.append("")
    lines.append("## 下周计划")
    lines.append("")
    lines.append("- （待补充）")
    lines.append("")
    lines.append("## 风险与阻塞")
    lines.append("")
    if bug_sum and bug_sum["open_p0p1"]:
        for x in bug_sum["open_p0p1"]:
            lines.append(f"- [ ] {x}")
    else:
        lines.append("- 无")
    lines.append("")

    return "\n".join(lines), f"周报-{d.isoformat()}.md"


# ---------- 主流程 ----------
def main():
    ap = argparse.ArgumentParser(description="项目总结/日报/周报 自动生成")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_summary = sub.add_parser("summary", help="项目总结")
    p_summary.add_argument("--project", required=True)
    p_summary.add_argument("--author", default="")
    p_summary.add_argument("--body", action="append", default=[])

    p_daily = sub.add_parser("daily", help="日报")
    p_daily.add_argument("--date", default=date.today().isoformat())
    p_daily.add_argument("--project", default="")
    p_daily.add_argument("--author", default="")
    p_daily.add_argument("--body", action="append", default=[])

    p_weekly = sub.add_parser("weekly", help="周报")
    p_weekly.add_argument("--date", default=date.today().isoformat())
    p_weekly.add_argument("--project", default="")
    p_weekly.add_argument("--author", default="")
    p_weekly.add_argument("--body", action="append", default=[])

    p_list = sub.add_parser("list", help="列出已生成报告")
    args = ap.parse_args()

    if args.cmd == "list":
        if not os.path.isdir(REPORTS_DIR):
            print("暂无报告")
            return
        for name in sorted(os.listdir(REPORTS_DIR), reverse=True):
            print(name)
        return

    os.makedirs(REPORTS_DIR, exist_ok=True)

    if args.cmd == "summary":
        content, fname = gen_summary(args.project, args.author, args.body)
    elif args.cmd == "daily":
        content, fname = gen_daily(args.project, args.author, args.body, args.date)
    elif args.cmd == "weekly":
        content, fname = gen_weekly(args.project, args.author, args.body, args.date)
    else:
        ap.print_help()
        return

    path = os.path.join(REPORTS_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"报告已生成: {path}")
    print("---")
    print(content)


if __name__ == "__main__":
    main()