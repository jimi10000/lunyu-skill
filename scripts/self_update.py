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
  5. 清理远端已删除的旧文件（只删上次安装清单内的文件；--no-prune 可关闭）
  6. 无新版 -> 提示已是最新

用户数据安全模型（重要）：
  更新期间用户数据 .lunyu/ 通过「同一分区原子换名」在施工区之间转移，
  绝不使用「先 rmtree 再 copytree」。
  任意时刻磁盘上都至少存在一份完整的用户数据：
      更新前    -> .lunyu/
      覆盖施工期 -> .lunyu.old.tmp/
      恢复完成  -> .lunyu/
  任何步骤失败（Ctrl-C / 磁盘满 / 进程被杀）都会自动把 .lunyu.old.tmp
  换回 .lunyu/，并清理所有临时目录，不留残留。

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
import json
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

DATA_DIR_NAME = ".lunyu"
# 更新施工期 .lunyu 的临时存放点（与 .lunyu 同分区，保证 os.replace 原子可用）
OLD_DATA_TMP = ".lunyu.old.tmp"
# 老版本（"删除+复制"实现）失败后残留的备份目录，见到即回收
LEGACY_BAK_TMP = ".lunyu.bak.tmp"
# 上次安装真正落盘的文件清单，prune 的唯一依据
MANIFEST_NAME = ".lunyu-manifest.json"
MANIFEST_VERSION = 1

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


def read_local_skill_name(skill_dir):
    """读已安装技能 SKILL.md 顶层 name（包名固化：决定自更新下载 URL）。"""
    path = os.path.join(skill_dir, "SKILL.md")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r"^name:[ \t]*[\"']?([A-Za-z0-9._-]+)[\"']?[ \t]*$", text, re.M)
    if not m:
        m = re.search(r"^[ \t]+name:[ \t]*[\"']?([A-Za-z0-9._-]+)[\"']?[ \t]*$", text, re.M)
    return m.group(1).strip() if m else None


def download_zip(dest_dir, remote_version, pkg_name="lunyu"):
    """下载最新版压缩包并解压，返回源码根目录。

    优先 Release 附件（干净的技能包），失败则回退分支归档。
    Release 附件名由已安装技能的 name 派生（包名固化），不写死 lunyu。
    """
    candidates = []
    mirror = os.environ.get("LUNYU_MIRROR", "").strip().rstrip("/")
    if mirror:
        candidates.append("%s/archive/refs/heads/%s.zip" % (mirror, BRANCH))
    if remote_version:
        tag = remote_version if remote_version.startswith("v") else "v" + remote_version
        candidates.append(
            "%s/releases/download/%s/%s-%s.zip" % (REPO, tag, pkg_name, tag)
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


# ---------------- 安装清单（prune 的唯一依据） ----------------
def read_manifest(skill_dir):
    """读上次安装落盘的文件清单。

    返回 set(相对路径)；不存在或无法解析一律返回 None —— 调用方必须保守跳过 prune，
    绝不靠路径前缀猜"这个文件曾经属于技能包"。
    """
    path = os.path.join(skill_dir, MANIFEST_NAME)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    files = data.get("files")
    if not isinstance(files, list):
        return None
    out = set()
    for rel in files:
        if isinstance(rel, str) and rel.strip():
            out.add(rel.strip().replace("\\", "/"))
    return out or None


def write_manifest(skill_dir, files):
    """原子写入本次安装清单（先写 .tmp 再 replace，避免半截 JSON）。"""
    path = os.path.join(skill_dir, MANIFEST_NAME)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {"version": MANIFEST_VERSION, "files": sorted(set(files))},
                f,
                ensure_ascii=False,
                indent=1,
            )
        os.replace(tmp, path)
        return True
    except OSError as e:
        print("警告: 写入 %s 失败: %s（下次更新将跳过旧文件清理）" % (MANIFEST_NAME, e))
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def _is_protected_rel(rel):
    """清单里若残留 KEEP_DIRS 下的路径，一律不碰（防御老版本产生的脏清单）。"""
    head = rel.replace("\\", "/").split("/", 1)[0]
    return head in KEEP_DIRS or rel.replace("\\", "/") in (
        MANIFEST_NAME, OLD_DATA_TMP, LEGACY_BAK_TMP
    )


def prune_removed_files(skill_dir, manifest, keep):
    """只删「上次清单里有 且 本次远端包里没有」的文件。

    不在 manifest 里的文件（= 用户自建/第三方投放）一律不碰。
    """
    removed = []
    for rel in sorted(manifest):
        if rel in keep or _is_protected_rel(rel):
            continue
        target = os.path.join(skill_dir, rel.replace("/", os.sep))
        if not os.path.isfile(target):
            continue
        try:
            os.remove(target)
            removed.append(rel)
        except OSError:
            pass
    return removed


# ---------------- 用户数据（.lunyu）搬运 ----------------
def _swap_dir(src, dst):
    """同分区原子换名；成功返回 True。dst 必须不存在。"""
    if not os.path.isdir(src) or os.path.exists(dst):
        return False
    os.replace(src, dst)
    return True


def restore_data(old_tmp, data_dir):
    """把施工期的 .lunyu.old.tmp 换回 .lunyu/（瞬间原子操作）。"""
    return _swap_dir(old_tmp, data_dir)


def rollback_data(old_tmp, data_dir):
    """失败兜底：把旧数据换回原位，永不抛异常。"""
    if not os.path.isdir(old_tmp) or os.path.isdir(data_dir):
        return os.path.isdir(data_dir)
    try:
        _swap_dir(old_tmp, data_dir)
    except OSError as e:
        print("严重: 回滚失败，用户数据仍留在 %s/（请手动 rename 回 .lunyu）: %s"
              % (OLD_DATA_TMP, e))
        return False
    return True


def _recover_tmp_dir(tmp_path, data_dir, label):
    """回收上一次中断留下的临时目录：数据丢失则救回，数据完好则丢弃残留。"""
    if not os.path.isdir(tmp_path):
        return
    if os.path.isdir(data_dir):
        print("提示: 清理上次更新残留的 %s（.lunyu 完好）" % label)
        shutil.rmtree(tmp_path, ignore_errors=True)
        return
    print("提示: 上次更新疑似中断，正在从 %s 恢复 .lunyu 数据" % label)
    try:
        _swap_dir(tmp_path, data_dir)
    except OSError as e:
        print("严重: 无法恢复 %s 里的用户数据: %s" % (label, e))


def apply_update(skill_dir, src_dir, prune=True):
    """用 src_dir 覆盖 skill_dir，返回 (写入文件数, 清理的旧文件列表)。

    数据销毁窗口已消除：全程只用 os.replace 搬动 .lunyu，
    不做「rmtree + copytree」，失败自动回滚。
    """
    data_dir = os.path.join(skill_dir, DATA_DIR_NAME)
    old_tmp = os.path.join(skill_dir, OLD_DATA_TMP)
    legacy_bak = os.path.join(skill_dir, LEGACY_BAK_TMP)

    _recover_tmp_dir(legacy_bak, data_dir, LEGACY_BAK_TMP)
    _recover_tmp_dir(old_tmp, data_dir, OLD_DATA_TMP)

    had_data = os.path.isdir(data_dir)
    try:
        # 1. 把用户数据原子挪出施工区（瞬时，磁盘上始终有完整一份）
        if had_data:
            try:
                os.replace(data_dir, old_tmp)
            except OSError as e:
                print("警告: 无法移动 .lunyu（%s），改为就地保留（本流程不写入 .lunyu）" % e)

        # 2. 覆盖写入技能文件（iter_files 已排除 KEEP_DIRS）
        written = []
        for rel in iter_files(src_dir):
            s = os.path.join(src_dir, rel.replace("/", os.sep))
            d = os.path.join(skill_dir, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)
            written.append(rel)

        # 3. 仅按上次清单清理远端已删文件；无清单则保守跳过
        removed = []
        if prune:
            manifest = read_manifest(skill_dir)
            if manifest is None:
                print("提示: 未找到 %s，跳过旧文件清理"
                      "（老版本升级上来的首次安装，不做猜测，用户自建文件一律保留）"
                      % MANIFEST_NAME)
            else:
                removed = prune_removed_files(skill_dir, manifest, set(written))

        # 4. 恢复用户数据，并确认落位后才算更新成功
        restore_data(old_tmp, data_dir)
        if had_data and not os.path.isdir(data_dir):
            raise RuntimeError("恢复 .lunyu 失败，已触发回滚")

        write_manifest(skill_dir, written)
        return len(written), removed
    except BaseException:
        pending = os.path.isdir(old_tmp)
        rollback_data(old_tmp, data_dir)
        if pending and had_data and os.path.isdir(data_dir):
            print("已回滚：.lunyu/ 已换回原位，用户数据无损（本次更新未生效）")
        raise
    finally:
        # 兜底：任何出口都不允许用户数据滞留在临时目录里
        if not os.path.isdir(data_dir) and os.path.isdir(old_tmp):
            rollback_data(old_tmp, data_dir)
        if os.path.isdir(data_dir):
            if os.path.isdir(old_tmp):
                shutil.rmtree(old_tmp, ignore_errors=True)
            if os.path.isdir(legacy_bak):
                shutil.rmtree(legacy_bak, ignore_errors=True)
        stale = os.path.join(skill_dir, MANIFEST_NAME + ".tmp")
        if os.path.exists(stale):
            try:
                os.remove(stale)
            except OSError:
                pass


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

    pkg_name = read_local_skill_name(skill_dir) or "lunyu"
    print("技能包名: %s（包名固化，自更新下载 URL 由其派生）" % pkg_name)

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
            src = download_zip(tmp, remote_version, pkg_name=pkg_name)
            print("安装覆盖 ...")
            written, removed = apply_update(
                skill_dir, src, prune=not args.no_prune
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:  # noqa: BLE001
        print("错误: 更新失败: %s" % e)
        print("数据安全: .lunyu/ 用户数据已自动回滚/保持在原位，未丢失")
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
