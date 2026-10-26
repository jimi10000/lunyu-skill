#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
self_update.py — 一键自更新 lunyu 技能包（跨平台，零第三方依赖）

适用场景：
  - 用 zip 安装包解压安装的用户（目录里没有 .git，git pull 用不了）
  - 用 git clone 安装的用户（同样可用，走 HTTP 覆盖，不强依赖 git）
  - Windows / macOS / Linux 全平台（不依赖 curl / unzip / rsync）

行为:
  1. 定位技能根目录（本脚本所在目录的上一级）
  2. 读本地版本（SKILL.md frontmatter，优先顶层 version，回退 metadata.version）
  3. 从 GitHub 拉远端最新版本号
  4. 有新版 -> 下载 zip（优先 Release 附件，回退分支归档）-> 覆盖（保留 .lunyu 数据）
  5. 清理远端已删除的旧文件（--no-prune 可关闭）
  6. 无新版 -> 提示已是最新

用法:
  python scripts/self_update.py            # 检查并（交互式）更新
  python scripts/self_update.py --check    # 只检查是否有新版，不改任何文件
  python scripts/self_update.py --yes      # 非交互，直接更新
  python scripts/self_update.py --force    # 跳过版本比较，强制重装

环境变量:
  LUNYU_REPO    GitHub 仓库 URL（默认 https://github.com/jimi10000/lunyu-skill）
  LUNYU_BRANCH  分支（默认 main）

退出码: 0=已是最新或更新成功 / 1=失败 / 2=有新版本但用户选择不更新(--check)
"""

import argparse
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile

REPO = os.environ.get("LUNYU_REPO", "https://github.com/jimi10000/lunyu-skill")
BRANCH = os.environ.get("LUNYU_BRANCH", "main")

# 覆盖时永不删除的目录（用户数据 / 本地仓库）
KEEP_DIRS = {".lunyu", ".git", "__pycache__"}

UA = "lunyu-self-update/1.0"


# ---------------- 版本解析 ----------------
def parse_version(text):
    """从 SKILL.md 全文解析版本号。

    优先级：frontmatter 顶层 version  >  metadata.version
    原因：技能市场解析器只读顶层，本地也必须以顶层为准；
    旧版本可能只写在 metadata 子层，故保留回退。
    """
    m = re.search(r"^---\s*$", text, re.M)
    body = text
    if m:
        rest = text[m.end():]
        m2 = re.search(r"^---\s*$", rest, re.M)
        if m2:
            body = rest[: m2.start()]

    # 1) 顶层：行首无缩进
    top = re.search(r"^version:\s*\"?([0-9][0-9A-Za-z.\-+]*)\"?\s*$", body, re.M)
    if top:
        return top.group(1)

    # 2) 回退：缩进的 metadata.version
    indented = re.search(
        r"^[ \t]+version:\s*\"?([0-9][0-9A-Za-z.\-+]*)\"?\s*$", body, re.M
    )
    if indented:
        return indented.group(1)

    # 3) 全文兜底（非 frontmatter 场景）
    any_ver = re.search(r"version:\s*\"?([0-9][0-9A-Za-z.\-+]*)\"?", text)
    return any_ver.group(1) if any_ver else ""


def vtuple(v):
    """语义化版本 -> 可比较元组。非数字段降级为 0，避免解析炸裂。"""
    v = v.lstrip("vV").strip()
    parts = re.split(r"[.\-+]", v)
    out = []
    for p in parts[:4]:
        out.append(int(p) if p.isdigit() else 0)
    while len(out) < 4:
        out.append(0)
    return tuple(out)


def is_newer(remote, local):
    """远端是否比本地新。"""
    if not remote or not local:
        return bool(remote)
    return vtuple(remote) > vtuple(local)


# ---------------- 网络 ----------------
def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _decode_api_json(raw):
    """GitHub contents 接口返回 JSON，content 字段是 base64。"""
    import base64
    import json

    j = json.loads(raw)
    if j.get("encoding") == "base64" and j.get("content"):
        return base64.b64decode(j["content"]).decode("utf-8", "replace")
    return ""


def _version_sources():
    """远端版本候选源，按优先级排列。

    国内直连 GitHub 时好时坏，故多源回退：
      镜像（可选） -> github raw -> raw.githubusercontent -> GitHub API
    """
    sources = []
    mirror = os.environ.get("LUNYU_MIRROR", "").strip().rstrip("/")
    if mirror:
        sources.append(("mirror", "%s/raw/%s/SKILL.md" % (mirror, BRANCH)))

    sources.append(("raw", "%s/raw/%s/SKILL.md" % (REPO, BRANCH)))

    if "github.com/" in REPO:
        slug = REPO.rstrip("/").split("github.com/")[-1]
        sources.append(
            ("cdn", "https://raw.githubusercontent.com/%s/%s/SKILL.md" % (slug, BRANCH))
        )
        sources.append(
            ("api", "https://api.github.com/repos/%s/contents/SKILL.md?ref=%s" % (slug, BRANCH))
        )
    return sources


def fetch_remote_version():
    """拉取远端 SKILL.md 里的版本号（多源回退，任一成功即可）。"""
    for name, url in _version_sources():
        try:
            raw = http_get(url).decode("utf-8", "replace")
            if name == "api":
                raw = _decode_api_json(raw)
            v = parse_version(raw)
            if v:
                return v
        except Exception:  # noqa: BLE001
            continue
    return ""


def download_zip(dest_dir, remote_version):
    """下载最新版压缩包并解压，返回源码根目录。

    优先 Release 附件（干净的技能包），失败则回退分支归档。
    """
    candidates = []
    mirror = os.environ.get("LUNYU_MIRROR", "").strip().rstrip("/")
    if mirror:
        candidates.append("%s/archive/refs/heads/%s.zip" % (mirror, BRANCH))
    if remote_version:
        tag = remote_version if remote_version.startswith("v") else "v" + remote_version
        candidates.append(
            "%s/releases/download/%s/lunyu-%s.zip" % (REPO, tag, tag)
        )
    candidates.append("%s/archive/refs/heads/%s.zip" % (REPO, BRANCH))

    last_err = None
    for url in candidates:
        try:
            data = http_get(url, timeout=120)
            zp = os.path.join(dest_dir, "pkg.zip")
            with open(zp, "wb") as f:
                f.write(data)
            with zipfile.ZipFile(zp) as z:
                z.extractall(dest_dir)
            os.remove(zp)
            root = find_skill_root(dest_dir)
            if root:
                return root
            last_err = "压缩包内未找到 SKILL.md"
        except urllib.error.HTTPError as e:
            last_err = "HTTP %s: %s" % (e.code, url)
        except Exception as e:  # noqa: BLE001
            last_err = str(e)

    raise RuntimeError("下载失败：%s" % (last_err or "无可用下载源"))


def find_skill_root(base):
    """在解压目录里定位含 SKILL.md 的那一层。

    Release 附件结构：lunyu/SKILL.md
    分支归档结构：lunyu-skill-main/SKILL.md
    """
    for root, dirs, names in os.walk(base):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        if "SKILL.md" in names:
            return root
    return None


# ---------------- 覆盖安装 ----------------
def iter_files(root):
    """遍历技能包内所有文件（相对路径），跳过保留目录。"""
    rels = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in KEEP_DIRS
        ]
        for n in filenames:
            full = os.path.join(dirpath, n)
            rel = os.path.relpath(full, root).replace("\\", "/")
            rels.append(rel)
    return rels


def apply_update(skill_dir, src_dir, prune=True):
    """用 src_dir 覆盖 skill_dir，保留 KEEP_DIRS，可选清理多余文件。"""
    # 1. 备份用户数据
    data_dir = os.path.join(skill_dir, ".lunyu")
    backup = None
    if os.path.isdir(data_dir):
        backup = os.path.join(skill_dir, ".lunyu.bak.tmp")
        if os.path.exists(backup):
            shutil.rmtree(backup)
        shutil.copytree(data_dir, backup)

    # 2. 覆盖写入
    written = 0
    for rel in iter_files(src_dir):
        s = os.path.join(src_dir, rel.replace("/", os.sep))
        d = os.path.join(skill_dir, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        written += 1

    # 3. 清理远端已删除的旧文件（保守：只删技能包内同名体系的文件）
    removed = []
    if prune:
        keep = set(iter_files(src_dir))
        for rel in iter_files(skill_dir):
            if rel in keep:
                continue
            # 用户自建文件（.lunyu 已排除）也一并保留，只删"曾属于技能包"的
            if rel.startswith("docs/") or rel.startswith("tests/") \
                    or rel.startswith("scripts/") or rel.startswith("templates/") \
                    or rel.startswith("references/") or "/" not in rel:
                try:
                    os.remove(os.path.join(skill_dir, rel.replace("/", os.sep)))
                    removed.append(rel)
                except OSError:
                    pass

    # 4. 恢复用户数据
    if backup and os.path.isdir(backup):
        if os.path.isdir(data_dir):
            shutil.rmtree(data_dir)
        shutil.copytree(backup, data_dir)
        shutil.rmtree(backup)

    return written, removed


# ---------------- 主流程 ----------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="lunyu 技能包一键自更新")
    ap.add_argument("--check", action="store_true", help="只检查是否有新版本，不修改文件")
    ap.add_argument("--yes", "-y", action="store_true", help="非交互，直接更新")
    ap.add_argument("--force", action="store_true", help="跳过版本比较，强制重装")
    ap.add_argument("--no-prune", action="store_true", help="不删除远端已删除的旧文件")
    args = ap.parse_args(argv)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    skill_dir = os.path.dirname(script_dir)

    if not os.path.isfile(os.path.join(skill_dir, "SKILL.md")):
        print("错误: 未在 %s 找到 SKILL.md，脚本位置不对" % skill_dir)
        return 1

    print("技能目录: %s" % skill_dir)

    with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8") as f:
        local_version = parse_version(f.read()) or "0.0.0"
    print("本地版本: %s" % local_version)

    print("检查远端版本 ...")
    remote_version = fetch_remote_version()
    if not remote_version:
        print("错误: 无法获取远端版本，请检查网络或设置 LUNYU_REPO")
        return 1
    print("远端版本: %s" % remote_version)

    if not args.force and not is_newer(remote_version, local_version):
        print("已是最新版本 (%s)，无需更新。" % local_version)
        return 0

    if args.check:
        print("发现新版本: %s -> %s" % (local_version, remote_version))
        print("（--check 模式，未做任何修改）")
        return 2

    if not args.force and not args.yes:
        try:
            ans = input("发现新版本 %s -> %s，是否更新？[y/N] " % (local_version, remote_version))
        except EOFError:
            ans = "n"
        if ans.strip().lower() != "y":
            print("已取消更新。")
            return 0

    try:
        tmp = tempfile.mkdtemp(prefix="lunyu-update-")
        try:
            print("下载 %s ..." % remote_version)
            src = download_zip(tmp, remote_version)
            print("安装覆盖 ...")
            written, removed = apply_update(
                skill_dir, src, prune=not args.no_prune
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:  # noqa: BLE001
        print("错误: 更新失败: %s" % e)
        print("提示: 也可手动下载 %s/releases 的 zip 覆盖安装" % REPO)
        return 1

    with open(os.path.join(skill_dir, "SKILL.md"), encoding="utf-8") as f:
        new_version = parse_version(f.read())
    print("更新完成: %s -> %s（写入 %d 个文件%s）" % (
        local_version, new_version, written,
        "，清理 %d 个旧文件" % len(removed) if removed else ""
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
