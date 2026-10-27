#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智能自进化：从经验库提取「应上升为技能规则」的候选，生成提案。

lunyu 的经验库（lessons.json）既存项目经验，也存「应上升为技能规则」的条目
（标记 skill:true 或 weight 达到阈值）。本脚本把它们提取出来，输出成
`<root>/.lunyu/evolution-proposals.md`，供人工确认后合并进 SKILL.md /
references / templates，随版本 bump 生效。

用法：
  python scripts/evolve.py [--root <项目根>] [--min-weight 3] [--out <文件>] [--json]
"""
import argparse
import json
import os
import sys


def find_root(start):
    start = os.path.abspath(start or os.getcwd())
    cur = start
    while True:
        if os.path.isdir(os.path.join(cur, ".git")) or os.path.isfile(
            os.path.join(cur, "SKILL.md")
        ):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return start
        cur = parent


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return {"lessons": []}
    if not isinstance(data, dict) or not isinstance(data.get("lessons"), list):
        return {"lessons": []}
    return data


def candidates(global_data, project_data, min_weight):
    seen = set()
    out = []
    for data in (global_data, project_data):
        for it in data.get("lessons", []):
            skill = it.get("skill") is True
            w = it.get("weight", 0) or 0
            if skill or w >= min_weight:
                key = (it.get("kind", ""), it.get("scene", ""), (it.get("text", "") or "")[:40])
                if key in seen:
                    continue
                seen.add(key)
                out.append(it)
    out.sort(key=lambda x: (x.get("weight", 0) or 0), reverse=True)
    return out


def render(items):
    lines = [
        "# 智能自进化 · 技能规则候选提案",
        "",
        "> 由 `scripts/evolve.py` 从经验库提取（标 `skill:true` 或权重≥阈值）。",
        "> 确认后合并进 SKILL.md / references / templates，随版本 bump 生效。",
        "> 用户的每一条纠正都是最高优先级输入。",
        "",
    ]
    if not items:
        lines.append(
            "（暂无候选——把踩坑/结论入经验库时标 `skill:true` 或提高 weight 即可入选）"
        )
        return "\n".join(lines)
    lines.append("## 候选规则（按权重降序）")
    lines.append("")
    for i, it in enumerate(items, 1):
        kind = it.get("kind", "结论")
        scene = it.get("scene", "")
        text = it.get("text", "")
        w = it.get("weight", 0) or 0
        reason = "skill:true" if it.get("skill") is True else "weight≥阈值"
        lines.append("### %d. [%s] %s" % (i, kind, scene))
        lines.append("")
        lines.append("- 内容：%s" % text)
        lines.append("- 权重：%s（入选理由：%s）" % (w, reason))
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="从经验库提取应上升为技能规则的候选")
    ap.add_argument("--root", help="项目根目录(默认自动查找 .git)")
    ap.add_argument("--min-weight", type=int, default=3, help="入选最小权重(默认3)")
    ap.add_argument(
        "--out", help="提案输出文件(默认 <root>/.lunyu/evolution-proposals.md)"
    )
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非 markdown")
    args = ap.parse_args()

    root = find_root(args.root)
    global_path = os.path.join(os.path.expanduser("~"), ".lunyu", "lessons.json")
    project_path = os.path.join(root, ".lunyu", "lessons.json")

    g = load(global_path)
    p = load(project_path)
    items = candidates(g, p, args.min_weight)

    if args.json:
        print(json.dumps(items, ensure_ascii=False, indent=2))
        return 0

    md = render(items)
    out = args.out or os.path.join(root, ".lunyu", "evolution-proposals.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md + "\n")
    print("提取候选 %d 条 → %s" % (len(items), out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
