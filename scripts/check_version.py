#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版本一致性校验：SKILL.md 顶层 / metadata / README 徽章 / CHANGELOG 顶部四处必须同步。

第三条第 7 项要求：
  三处必须同步：SKILL.md 顶层 frontmatter 的 version、SKILL.md 内 metadata 段的 version、
  README 徽章，CHANGELOG 顶部还要跟一条。
  不一致时非零退出；接入 pack.py 打包前校验与 CI。

用法：
  python scripts/check_version.py            # 比对四处版本号，一致返回 0，不一致返回 1
  python scripts/check_version.py --json     # 输出 JSON 结果，适合挂 CI

退出码：0=一致 / 1=不一致
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# SKILL.md 顶层 version（frontmatter 根级）
TOP_VERSION_RE = re.compile(r"^version:[ \t]*[\"']?([0-9][^\"'\r\n]*)[\"']?[ \t]*$", re.M)
# metadata 子层 version（缩进的 version:）
META_VERSION_RE = re.compile(r"^[ \t]+version:[ \t]*[\"']?([0-9][^\"'\r\n]*)[\"']?[ \t]*$", re.M)
# README 徽章里的版本号（只取 x.y.z，不带 -blue.svg 后缀）
BADGE_VERSION_RE = re.compile(r"badge/version-([0-9]+\.[0-9]+\.[0-9]+)")
# CHANGELOG 顶部第一个版本条目
CHANGELOG_TOP_RE = re.compile(r"^## \[([0-9][^\]\r\n]*)\]", re.M)


def read_skill_top_version(root):
    path = os.path.join(root, "SKILL.md")
    if not os.path.isfile(path):
        return None
    text = open(path, encoding="utf-8").read()
    m = TOP_VERSION_RE.search(text)
    return m.group(1).strip() if m else None


def read_skill_meta_version(root):
    path = os.path.join(root, "SKILL.md")
    if not os.path.isfile(path):
        return None
    text = open(path, encoding="utf-8").read()
    m = META_VERSION_RE.search(text)
    return m.group(1).strip() if m else None


def read_readme_badge_version(root):
    path = os.path.join(root, "README.md")
    if not os.path.isfile(path):
        return None
    text = open(path, encoding="utf-8").read()
    m = BADGE_VERSION_RE.search(text)
    return m.group(1).strip() if m else None


def read_changelog_top_version(root):
    path = os.path.join(root, "CHANGELOG.md")
    if not os.path.isfile(path):
        return None
    text = open(path, encoding="utf-8").read()
    m = CHANGELOG_TOP_RE.search(text)
    return m.group(1).strip() if m else None


def check(root):
    """返回 (sources, mismatches)。sources 为 {名称: 版本号}，mismatches 为不一致项列表。"""
    sources = {
        "SKILL.md 顶层": read_skill_top_version(root),
        "SKILL.md metadata": read_skill_meta_version(root),
        "README 徽章": read_readme_badge_version(root),
        "CHANGELOG 顶部": read_changelog_top_version(root),
    }
    present = {k: v for k, v in sources.items() if v is not None}
    mismatches = []
    if present:
        first = next(iter(present.values()))
        for k, v in present.items():
            if v != first:
                mismatches.append((k, v, first))
    return sources, mismatches


def main():
    ap = argparse.ArgumentParser(description="版本一致性校验")
    ap.add_argument("--root", default=ROOT, help="技能根目录（默认脚本上一级）")
    ap.add_argument("--json", action="store_true", dest="as_json", help="输出 JSON 结果")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    sources, mismatches = check(root)

    if args.as_json:
        print(json.dumps({
            "sources": sources,
            "consistent": not mismatches,
            "mismatches": [{"source": s, "found": v, "expected": e} for s, v, e in mismatches],
        }, ensure_ascii=False, indent=2))
    else:
        for k, v in sources.items():
            print("  %s: %s" % (k, v if v is not None else "(未找到)"))
        if mismatches:
            for s, v, e in mismatches:
                print("  [X] %s=%s，应为 %s" % (s, v, e), file=sys.stderr)
            print("结论：版本不一致", file=sys.stderr)
            return 1
        print("结论：版本一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())