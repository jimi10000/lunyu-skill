#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打包 lunyu 技能包为可分发的 zip，并生成自更新用的文件清单。

设计要点（君子求诸己：发布链路自己也得自动化）：
  - 纯标准库，无外部依赖
  - 版本号默认从 SKILL.md 顶层 version 读（与市场解析口径一致），不靠人传
  - 包名从 SKILL.md 顶层 name 读（**包名固化**：zip 文件名、包内顶层目录、
    self_update 下载 URL、市场元数据四处来源唯一）。改 SKILL.md 的 name，
    重新打包即可，自更新链路自动跟随；--name 传了不一致的值只警告不生效
  - 生成 .lunyu-manifest.json 放进包内，让 self_update.py 能做精准 prune
    （没有清单时自更新只能保守跳过清理，旧文件会残留）
  - 排除工作数据 .lunyu/、缓存 __pycache__、版本库 .git、上次产物 dist/
  - 输出 sha256，便于交付核对（刷包只认 sha256，不认字节数）

用法:
  python scripts/pack.py                       # 打进 dist/
  python scripts/pack.py --out ./release       # 指定输出目录
  python scripts/pack.py --version 1.2.1       # 覆盖版本号
  python scripts/pack.py --no-manifest         # 不写清单（调试用）
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_ROOT = os.path.dirname(HERE)

EXCLUDE_DIRS = {".git", "__pycache__", ".lunyu", "dist", ".pytest_cache", ".idea", ".vscode", "docs", "tests", ".github"}
EXCLUDE_FILES = {".gitignore", ".DS_Store", ".lunyu-manifest.json", "README.md", "CHANGELOG.md", "CONTRIBUTING.md", "LICENSE"}
EXCLUDE_SUFFIX = (".pyc", ".pyo", ".tmp", ".bak", ".orig")
MANIFEST_NAME = ".lunyu-manifest.json"
MANIFEST_VERSION = 1


def read_skill_version(skill_root):
    """从 SKILL.md 顶层 YAML 读 version（顶层优先，缩进子层只作回退）。"""
    path = os.path.join(skill_root, "SKILL.md")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^version:[ \t]*[\"']?([0-9][^\"'\r\n]*)[\"']?[ \t]*$", text, re.M)
    if not m:
        m = re.search(r"^[ \t]+version:[ \t]*[\"']?([0-9][^\"'\r\n]*)[\"']?[ \t]*$", text, re.M)
    return m.group(1).strip() if m else None


def read_skill_name(skill_root):
    """从 SKILL.md 顶层 YAML 读 name（包名固化唯一来源）。"""
    path = os.path.join(skill_root, "SKILL.md")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^name:[ \t]*[\"']?([A-Za-z0-9._-]+)[\"']?[ \t]*$", text, re.M)
    if not m:
        m = re.search(r"^[ \t]+name:[ \t]*[\"']?([A-Za-z0-9._-]+)[\"']?[ \t]*$", text, re.M)
    return m.group(1).strip() if m else None


def collect_files(skill_root):
    """收集需要入包的相对路径（统一 / 分隔）。"""
    out = []
    for root, dirs, files in os.walk(skill_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            if name in EXCLUDE_FILES or name.endswith(EXCLUDE_SUFFIX):
                continue
            rel = os.path.relpath(os.path.join(root, name), skill_root).replace("\\", "/")
            out.append(rel)
    return sorted(out)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_pack_check(root):
    """调用 pack_check.py 做打包前清单双向校验，返回其退出码。"""
    import subprocess
    check_script = os.path.join(HERE, "pack_check.py")
    try:
        proc = subprocess.run(
            [sys.executable, check_script, "--root", root],
            cwd=SKILL_ROOT,
        )
        return proc.returncode
    except OSError as e:
        print("警告: 无法运行打包校验: %s" % e)
        return None


def _run_version_check(root):
    """调用 check_version.py 做打包前版本一致性校验，返回其退出码。"""
    import subprocess
    ver_script = os.path.join(HERE, "check_version.py")
    try:
        proc = subprocess.run(
            [sys.executable, ver_script, "--root", root],
            cwd=SKILL_ROOT,
        )
        return proc.returncode
    except OSError as e:
        print("警告: 无法运行版本校验: %s" % e)
        return 1


def main():
    ap = argparse.ArgumentParser(description="打包 lunyu 技能包（zip + 自更新清单 + sha256）")
    ap.add_argument("--root", default=SKILL_ROOT, help="技能根目录（默认脚本上一级）")
    ap.add_argument("--out", default=None, help="输出目录（默认 <root>/dist）")
    ap.add_argument("--version", default=None, help="覆盖版本号（默认读 SKILL.md）")
    ap.add_argument("--name", default=None, help="包内顶层目录名（默认读 SKILL.md 顶层 name，固化；传不一致只警告）")
    ap.add_argument("--no-manifest", action="store_true", help="不生成清单文件")
    ap.add_argument("--no-check", action="store_true", help="跳过打包前清单双向校验（仅调试用）")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isfile(os.path.join(root, "SKILL.md")):
        print("错误: %s 下没有 SKILL.md，不像技能根目录" % root)
        return 1

    version = args.version or read_skill_version(root)
    if not version:
        print("错误: 读不到版本号，用 --version 指定")
        return 1
    version = version.lstrip("vV")

    # 包名固化：始终以 SKILL.md 顶层 name 为唯一来源，--name 传不一致只警告
    pkg_name = read_skill_name(root) or "lunyu"
    if args.name and args.name != pkg_name:
        print(u"警告: --name=%r 与 SKILL.md 顶层 name=%r 不一致，按固化规则采用 SKILL.md 的"
              % (args.name, pkg_name))

    # 第三条第 6 项：打包前先做清单双向校验，失败即中断
    if not args.no_check:
        check = _run_pack_check(root)
        if check is not None and check != 0:
            print("错误: 打包清单校验未通过，禁止打包（--no-check 可跳过，仅调试用）")
            return 1

    # 第三条第 7 项：打包前校验版本四处一致（SKILL.md 顶层/metadata/README 徽章/CHANGELOG 顶部）
    if not args.no_check:
        _rc = _run_version_check(root)
        if _rc != 0:
            print("错误: 版本一致性校验未通过，禁止打包（--no-check 可跳过，仅调试用）")
            return 1

    out_dir = os.path.abspath(args.out or os.path.join(root, "dist"))
    os.makedirs(out_dir, exist_ok=True)
    zip_path = os.path.join(out_dir, "%s-v%s.zip" % (pkg_name, version))

    files = collect_files(root)
    if not files:
        print("错误: 没有可打包的文件")
        return 1

    stage = tempfile.mkdtemp(prefix="lunyu-pack-")
    try:
        pkg_root = os.path.join(stage, pkg_name)
        for rel in files:
            src = os.path.join(root, rel.replace("/", os.sep))
            dst = os.path.join(pkg_root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)

        if not args.no_manifest:
            with open(os.path.join(pkg_root, MANIFEST_NAME), "w", encoding="utf-8") as f:
                json.dump({"version": MANIFEST_VERSION, "files": files},
                          f, ensure_ascii=False, indent=1)

        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for base, _dirs, names in os.walk(pkg_root):
                for name in names:
                    full = os.path.join(base, name)
                    rel = os.path.relpath(full, stage).replace("\\", "/")
                    z.write(full, rel)
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    size_kb = os.path.getsize(zip_path) / 1024.0
    print("打包完成: %s" % zip_path)
    print("版本: v%s  文件数: %d  体积: %.1f KB" % (version, len(files), size_kb))
    print("sha256: %s" % sha256_of(zip_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
