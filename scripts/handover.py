#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交接产物 - 告诸往而知来者（把「上次做到哪」写给下一个接手的 AI/人）

解决 AI 协作最实际的问题：换一个 AI、或者会话上下文爆了重新开，
新接手的不知道上次做到哪、为什么这么定、哪些坑已经踩过。
于是重新问一遍、重新试一遍，甚至把已经否决的方案又做一遍。

git 里有代码，但 git 里没有「决策理由」和「中间状态」。
HANDOVER.md 补的就是这一块——五段固定格式：

  1. 当前状态     分支 / 工作区是否干净 / 最近提交 / 做到第几步
  2. 已完成清单   最近的提交，带 sha，能直接 git show
  3. 下一步       具体到动作（人工填，脚本给提示）
  4. 未决决策     还没定的取舍 + 当时的理由 + ADR 链接
  5. 已知坑       本次踩过的、别再踩的（从经验库自动带出）

前 3 段脚本能自动填，后 2 段给骨架和自动候选，人工确认。

论语出处：《论语·学而》「告诸往而知来者」——
把过去发生过的事讲清楚，对方才能知道接下来怎么做。

退出码: 0=完成 / 1=写入失败
用法:
  python scripts/handover.py                 # 生成 HANDOVER.md
  python scripts/handover.py --step 5        # 标注进行到 Step 5
  python scripts/handover.py --note "xxx"    # 追加一条备注
  python scripts/handover.py --read          # 打印现有交接文档
  python scripts/handover.py --json          # 机器可读
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

HANDOVER_NAME = "HANDOVER.md"


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


def read_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (ValueError, OSError):
        return default


def read_text(path):
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return ""


def git(root, args):
    try:
        r = subprocess.run(
            ["git", "-C", root] + list(args),
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def collect(root, step=None, note=None):
    """自动采集能采集的，人工部分留占位。"""
    branch = git(root, ["rev-parse", "--abbrev-ref", "HEAD"]) or "（非 git 仓库）"
    status = git(root, ["status", "--porcelain"])
    dirty = [l for l in status.splitlines() if l.strip()]
    head = git(root, ["log", "-1", "--format=%h %s"])
    log = git(root, ["log", "-8", "--format=%h|%ad|%s", "--date=short"])
    commits = []
    for line in log.splitlines():
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({"sha": parts[0], "date": parts[1], "subject": parts[2]})

    # 未关闭缺陷
    bugs = (read_json(os.path.join(root, ".lunyu", "bugs.json"), {"bugs": []}) or {}).get("bugs", [])
    open_bugs = [b for b in bugs if b.get("status") not in ("关闭",)]
    # 最近经验（按 hits/date 取前 8）
    lessons = (read_json(os.path.join(root, ".lunyu", "lessons.json"), {"lessons": []}) or {}).get("lessons", [])
    lessons_sorted = sorted(
        lessons, key=lambda x: (-(x.get("hits") or 0), str(x.get("date") or "")), reverse=False
    )[:8]
    # ADR 目录
    adr_dir = os.path.join(root, ".lunyu", "adr")
    adrs = []
    if os.path.isdir(adr_dir):
        try:
            adrs = sorted(f for f in os.listdir(adr_dir) if f.endswith(".md"))[-10:]
        except OSError:
            adrs = []
    # 最近报告
    rep_dir = os.path.join(root, ".lunyu", "reports")
    reports = []
    if os.path.isdir(rep_dir):
        try:
            reports = sorted(f for f in os.listdir(rep_dir) if f.endswith(".md"))[-5:]
        except OSError:
            reports = []

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "root": root,
        "step": step,
        "note": note,
        "branch": branch,
        "head": head,
        "dirty": dirty[:20],
        "dirty_count": len(dirty),
        "commits": commits,
        "open_bugs": open_bugs[:10],
        "open_bug_count": len(open_bugs),
        "lessons": lessons_sorted,
        "adrs": adrs,
        "reports": reports,
    }


def render(info):
    L = []
    L.append("# 交接说明（HANDOVER）")
    L.append("")
    L.append("> 本文件由 `python scripts/handover.py` 生成，供下一个接手的 AI / 同事阅读。")
    L.append("> **新会话开工第一件事是读这个文件，而不是问用户「你要做什么」。**")
    L.append("")
    L.append("- 生成时间：%s" % info["generated_at"])
    L.append("- 项目路径：`%s`" % info["root"])
    L.append("")

    L.append("## 1. 当前状态")
    L.append("")
    L.append("- 分支：`%s`" % info["branch"])
    L.append("- 最近提交：%s" % (info["head"] or "无"))
    L.append("- 进行到：%s" % ("Step %s" % info["step"] if info["step"] else "【待填：第几步】"))
    if info["dirty_count"]:
        L.append("- 工作区：**有 %d 个未提交文件**（可能做到一半）" % info["dirty_count"])
        for d in info["dirty"]:
            L.append("  - `%s`" % d.strip())
    else:
        L.append("- 工作区：干净，代码都已提交")
    if info["open_bug_count"]:
        L.append("- 未关闭缺陷：**%d 条**" % info["open_bug_count"])
        for b in info["open_bugs"][:5]:
            L.append("  - %s [%s] %s" % (b.get("id", "?"), b.get("priority", "?"), b.get("title", "")))
    L.append("")

    L.append("## 2. 已完成清单")
    L.append("")
    if info["commits"]:
        L.append("| sha | 日期 | 说明 |")
        L.append("|---|---|---|")
        for c in info["commits"]:
            L.append("| `%s` | %s | %s |" % (c["sha"], c["date"], c["subject"].replace("|", "\\|")))
    else:
        L.append("无提交记录。")
    L.append("")
    L.append("（另可 `git log --oneline -20` 看完整历史）")
    L.append("")

    L.append("## 3. 下一步")
    L.append("")
    if info["note"]:
        L.append("- %s" % info["note"])
    L.append("- 【待填：具体到动作，例如「跑 scripts/impact.py 确认 pay.py 调用方，再改 refund()」】")
    L.append("- 【待填：卡在哪、需要谁拍板】")
    L.append("")

    L.append("## 4. 未决决策（含理由）")
    L.append("")
    if info["adrs"]:
        L.append("已有 ADR：")
        for a in info["adrs"]:
            L.append("- `.lunyu/adr/%s`" % a)
        L.append("")
    L.append("- 【待填：还没定的取舍 + 当时为什么犹豫】")
    L.append("- 【待填：已被否决的方案，别让下一个接手的又做一遍】")
    L.append("")

    L.append("## 5. 已知坑（本次踩过，别再踩）")
    L.append("")
    if info["lessons"]:
        for it in info["lessons"]:
            scene = it.get("scene") or it.get("场景") or ""
            sol = it.get("solution") or it.get("结论") or ""
            L.append("- **%s** —— %s" % (scene, sol))
    else:
        L.append("经验库为空。踩坑记得入库：`python scripts/lessons.py add --scene \"...\" --solution \"...\"`")
    L.append("")
    L.append("---")
    L.append("")
    L.append("更新：`python scripts/handover.py --step <第几步> --note \"下一步要做什么\"`")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="交接产物 - 告诸往而知来者")
    ap.add_argument("--root", help="项目根目录（默认向上找 .git）")
    ap.add_argument("--step", help="标注当前进行到第几步")
    ap.add_argument("--note", help="追加一条「下一步」备注")
    ap.add_argument("--out", help="输出路径（默认项目根 HANDOVER.md）")
    ap.add_argument("--read", action="store_true", help="打印现有交接文档，不重新生成")
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root or find_root())
    out_path = os.path.abspath(args.out or os.path.join(root, HANDOVER_NAME))

    if args.read:
        text = read_text(out_path)
        if not text:
            print("还没有交接文档。生成: python scripts/handover.py")
            return 1
        print(text)
        return 0

    info = collect(root, args.step, args.note)
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0

    text = render(info)
    d = os.path.dirname(out_path)
    if d and not os.path.isdir(d):
        os.makedirs(d, exist_ok=True)
    try:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError as e:
        print("错误: 写入失败 %s (%s)" % (out_path, e), file=sys.stderr)
        return 1

    print("交接文档已生成: %s" % out_path)
    print("")
    print("  自动填好: 分支 / 提交 / 工作区状态 / 未关闭缺陷 / 已知坑")
    print("  需要人工补: 第 3 段「下一步」、第 4 段「未决决策」")
    print("")
    print("  新会话开工先读它: python scripts/handover.py --read")
    return 0


if __name__ == "__main__":
    sys.exit(main())
