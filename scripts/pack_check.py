#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包清单双向校验：正文引用的文件必须全部进包；包内文件必须有归属。

第三条第 6 项要求：
  正向：SKILL.md / references/ 正文引用的 references|scripts|templates 文件，
        必须存在于仓库（进而全部进包），缺一个 = 「缺少必需资源」。
  反向：包内出现的文件，要么被正文引用，要么有明确归属（清单 / 种子数据 /
        主文件 / 被 script-index 兜底索引），否则确认是否该进包。

用法：
  python scripts/pack_check.py                 # 校验当前仓库（不打包）
  python scripts/pack_check.py --zip out/lunyu-v1.2.9.zip   # 校验已打好的包

退出码：0=通过 / 1=有阻断（引用缺失或反向无归属）
"""
import argparse
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_ROOT = os.path.dirname(HERE)

# 正文里出现的相对路径引用（平台目录）
REF_RE = re.compile(r"(references|scripts|templates)/[A-Za-z0-9._\-\u4e00-\u9fff/]+\.(md|py|sh|json)")

# 允许出现在包内、但正文未直接点名的文件（有明确归属）
ALLOWED_EXTRA = {
    "SKILL.md",
    ".lunyu-manifest.json",
    "references/seed-lessons.json",
}

# 反向比对时，被 script-index 兜底索引的脚本（正文只列了常用项，
# 完整索引在 references/script-index.md）
SCRIPT_INDEX_NAMES = {
    "flow.py", "logkit.py", "preflight.py", "adr.py", "bug_ledger.py",
    "release_note.py", "report.py", "scheduler.py", "daily_report.sh",
    "release.py", "send_mail.py", "build_apk.sh", "vm_test.sh",
    "github-publish.sh", "lessons.py", "patrol.py", "self_update.py",
    "self_update.sh", "pack.py", "evolve.py", "pack_check.py",
}


def _refs_from_docs(root):
    """收集 SKILL.md 与 references/ 正文引用的平台路径。"""
    refs = set()
    root = os.path.abspath(root)
    for dirpath, _dirs, files in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
        if rel_dir == ".":
            rel_dir = ""
        if rel_dir not in ("", "references", "templates"):
            continue
        for name in files:
            if not name.endswith((".md", ".py", ".sh", ".json")):
                continue
            path = os.path.join(dirpath, name)
            try:
                text = open(path, encoding="utf-8").read()
            except OSError:
                continue
            for m in REF_RE.finditer(text):
                refs.add(m.group(0))
    return refs


def _repo_files(root):
    """仓库内平台目录的实际文件清单。"""
    files = set()
    for top in ("references", "scripts", "templates"):
        for dirpath, _dirs, names in os.walk(os.path.join(root, top)):
            for n in names:
                rel = os.path.relpath(os.path.join(dirpath, n), root).replace("\\", "/")
                files.add(rel)
    return files


def _pkg_files(zip_path):
    """包内实际文件清单（去掉顶层技能目录前缀）。"""
    files = set()
    with zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.endswith("/"):
                continue
            parts = n.split("/", 1)
            if len(parts) == 2 and parts[0]:
                files.add(parts[1])
            elif len(parts) == 1:
                files.add(parts[0])
    return files


def check(root, root_zip=None):
    """执行双向校验，返回 (ok_list, bad_list, extra_list)。"""
    ok, bad, extra = [], [], []

    refs = _refs_from_docs(root)
    repo = _repo_files(root)
    pkg = _pkg_files(root_zip) if root_zip else repo

    # 正向：正文引用必须存在于包
    missing = sorted(r for r in refs if r not in pkg)
    if not missing:
        ok.append("正向：正文引用的 %d 个文件全部在包内" % len(refs))
    else:
        bad.append("正向：正文引用了但包内缺失 %s" % missing[:10])

    # 反向：包内文件必须有归属
    unexplained = []
    for f in sorted(pkg):
        if f in refs or f in ALLOWED_EXTRA:
            continue
        base = os.path.basename(f)
        if f.startswith("scripts/") and base in SCRIPT_INDEX_NAMES:
            continue
        unexplained.append(f)
    if not unexplained:
        ok.append("反向：包内全部文件有归属（正文引用 / 索引 / 清单 / 种子）")
    else:
        extra.append("反向：包内未在正文点名的文件 %s" % unexplained)

    return ok, bad, extra


def main():
    ap = argparse.ArgumentParser(description="打包清单双向校验")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="技能根目录（默认脚本上一级）")
    ap.add_argument("--zip", default=None, help="校验已打好的 zip（默认校验当前仓库）")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isfile(os.path.join(root, "SKILL.md")):
        print("错误: %s 下没有 SKILL.md，不像技能根目录" % root, file=sys.stderr)
        return 1

    if args.zip and not os.path.isfile(args.zip):
        print("错误: zip 不存在: %s" % args.zip, file=sys.stderr)
        return 1

    ok, bad, extra = check(root, args.zip)

    for o in ok:
        print("  [OK] %s" % o)
    for e in extra:
        print("  [!] %s" % e)
    for b in bad:
        print("  [X] %s" % b, file=sys.stderr)

    if bad:
        print("结论：有阻断项，禁止发布", file=sys.stderr)
        return 1
    print("结论：通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())