#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""版本提升：一次改齐 SKILL.md 顶层 / metadata / README 徽章 / CHANGELOG 顶部。

第三条第 7 项要求：
  从 SKILL.md 读出当前版本或按提交信息推下一版（feat→minor、fix→patch、breaking→major），
  一次改齐并打印建议 tag 与命令，不负责打 tag。

用法：
  python scripts/bump.py                     # 按最近提交信息推下一版
  python scripts/bump.py --version 1.3.0       # 显式指定新版本
  python scripts/bump.py --dry-run            # 只打印改动，不写文件

退出码：0=成功 / 1=失败（无法推断版本等）
"""
import argparse
import datetime
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

TOP_VERSION_RE = re.compile(r"^(version:[ \t]*[\"']?)([0-9][^\"'\r\n]*)([\"']?[ \t]*)$", re.M)
META_VERSION_RE = re.compile(r"^([ \t]+version:[ \t]*[\"']?)([0-9][^\"'\r\n]*)([\"']?[ \t]*)$", re.M)
BADGE_VERSION_RE = re.compile(r"(badge/version-)([0-9]+\.[0-9]+\.[0-9]+)")


def read_current_version():
    path = os.path.join(ROOT, "SKILL.md")
    text = open(path, encoding="utf-8").read()
    m = TOP_VERSION_RE.search(text)
    return m.group(2).strip() if m else None


def read_last_commit_type():
    """按最近提交信息推下一版：breaking→major、feat→minor、其余→patch。"""
    try:
        log = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%s"],
            cwd=ROOT, text=True, stderr=subprocess.DEVNULL,
        )
    except Exception:
        return "patch"
    msg = log.strip()
    if re.search(r"^[A-Za-z]+!:", msg) or "BREAKING CHANGE" in msg:
        return "major"
    if re.match(r"^feat", msg):
        return "minor"
    return "patch"


def bump_version(current, part):
    major, minor, patch = (int(x) for x in current.split(".")[:3])
    if part == "major":
        major += 1
        minor = patch = 0
    elif part == "minor":
        minor += 1
        patch = 0
    else:
        patch += 1
    return "%d.%d.%d" % (major, minor, patch)


def main():
    ap = argparse.ArgumentParser(description="版本提升")
    ap.add_argument("--version", default=None, help="显式指定新版本号")
    ap.add_argument("--dry-run", action="store_true", help="只打印改动，不写文件")
    args = ap.parse_args()

    current = read_current_version()
    if not current:
        print("错误: 无法从 SKILL.md 读到当前版本号", file=sys.stderr)
        return 1

    if args.version:
        new_version = args.version
    else:
        part = read_last_commit_type()
        new_version = bump_version(current, part)
        print("最近提交类型推断: %s（%s → %s）" % (part, current, new_version))

    if not re.match(r"^\d+\.\d+\.\d+$", new_version):
        print("错误: 新版本号不合规: %s（需 MAJOR.MINOR.PATCH）" % new_version, file=sys.stderr)
        return 1

    # SKILL.md 顶层
    skill_path = os.path.join(ROOT, "SKILL.md")
    skill_text = open(skill_path, encoding="utf-8").read()
    m1 = TOP_VERSION_RE.search(skill_text)
    if not m1:
        print("错误: SKILL.md 顶层 version 未找到", file=sys.stderr)
        return 1
    new_skill = skill_text[:m1.start()] + m1.group(1) + new_version + m1.group(3) + skill_text[m1.end():]

    # SKILL.md metadata 段（第二个缩进的 version）
    m2 = META_VERSION_RE.search(new_skill)
    if not m2:
        print("错误: SKILL.md metadata 段 version 未找到", file=sys.stderr)
        return 1
    new_skill = new_skill[:m2.start()] + m2.group(1) + new_version + m2.group(3) + new_skill[m2.end():]

    # README 徽章
    readme_path = os.path.join(ROOT, "README.md")
    readme_text = open(readme_path, encoding="utf-8").read()
    bm = BADGE_VERSION_RE.search(readme_text)
    if not bm:
        print("警告: README 徽章版本号未找到，跳过", file=sys.stderr)
    new_readme = readme_text[:bm.start()] + bm.group(1) + new_version + readme_text[bm.end():] if bm else readme_text

    # CHANGELOG 顶部插一条：插在头部说明之后、第一个版本条目之前
    changelog_path = os.path.join(ROOT, "CHANGELOG.md")
    changelog_text = open(changelog_path, encoding="utf-8").read()
    today = datetime.date.today().isoformat()
    new_entry = "## [%s] - %s\n\n" % (new_version, today)
    first_entry = changelog_text.find("\n## [")
    if first_entry == -1:
        first_entry = changelog_text.find("## [")
    if first_entry == -1:
        # 没有版本条目，直接追加到头部说明后
        first_entry = len(changelog_text)
    else:
        # 定位到 "## [" 所在行的行首
        first_entry = changelog_text.rfind("\n", 0, first_entry) + 1
    new_changelog = changelog_text[:first_entry] + new_entry + changelog_text[first_entry:]

    if args.dry_run:
        print("当前版本: %s" % current)
        print("新版本:   %s" % new_version)
        print("将修改: SKILL.md 顶层 / SKILL.md metadata / README 徽章 / CHANGELOG 顶部")
        print("建议 tag: v%s" % new_version)
        print("建议命令: git add -A && git commit -m \"chore: v%s\" && git tag v%s" % (new_version, new_version))
        return 0

    with open(skill_path, "w", encoding="utf-8") as f:
        f.write(new_skill)
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_readme)
    with open(changelog_path, "w", encoding="utf-8") as f:
        f.write(new_changelog)

    print("已改齐: SKILL.md 顶层 / metadata / README 徽章 / CHANGELOG 顶部 → %s" % new_version)
    print("建议 tag: v%s" % new_version)
    print("建议命令: git add -A && git commit -m \"chore: v%s\" && git tag v%s" % (new_version, new_version))
    return 0


if __name__ == "__main__":
    sys.exit(main())