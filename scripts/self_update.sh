#!/usr/bin/env bash
# ============================================================
# self_update.sh — 一键自更新 lunyu 技能包
#
# 已安装用户运行本脚本，自动从 GitHub 拉取最新版并覆盖本地技能目录。
# 让「更新」从手动拷贝变成一条命令。
#
# 用法:
#   ./scripts/self_update.sh
#
# 行为:
#   1. 定位本技能根目录（脚本所在目录的上一级）
#   2. 检查当前版本（SKILL.md frontmatter metadata.version）
#   3. 从 GitHub 拉取远端最新版本号
#   4. 有新版则下载 zip 并解压覆盖（保留 .lunyu 数据文件）
#   5. 无新版则提示已是最新
#
# 环境变量:
#   LUNYU_REPO    GitHub 仓库（默认 https://github.com/jimi10000/lunyu-skill）
#   LUNYU_BRANCH  分支（默认 main）
#   LUNYU_FORCE=1 强制更新（跳过版本比较）
#
# 退出码: 0=已是最新或更新成功 / 1=失败
# ============================================================
set -euo pipefail

REPO="${LUNYU_REPO:-https://github.com/jimi10000/lunyu-skill}"
BRANCH="${LUNYU_BRANCH:-main}"
FORCE="${LUNYU_FORCE:-0}"

# ---------- 定位技能根目录 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILL_NAME="$(basename "$SKILL_DIR")"

echo "技能目录: $SKILL_DIR"

# ---------- 读取本地版本 ----------
LOCAL_VERSION=""
if [ -f "$SKILL_DIR/SKILL.md" ]; then
  LOCAL_VERSION=$(grep -E '^\s+version:' "$SKILL_DIR/SKILL.md" | head -1 | sed -E 's/.*version:\s*"?([^"]*)"?/\1/')
fi
if [ -z "$LOCAL_VERSION" ]; then
  LOCAL_VERSION="0.0.0"
fi
echo "本地版本: $LOCAL_VERSION"

# ---------- 拉取远端版本 ----------
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "检查远端版本 ..."
REMOTE_VERSION=""
if command -v curl >/dev/null 2>&1; then
  REMOTE_VERSION=$(curl -fsSL "$REPO/raw/$BRANCH/SKILL.md" 2>/dev/null | grep -E '^\s+version:' | head -1 | sed -E 's/.*version:\s*"?([^"]*)"?/\1/') || true
fi
if [ -z "$REMOTE_VERSION" ] && command -v powershell.exe >/dev/null 2>&1; then
  REMOTE_VERSION=$(powershell.exe -NoProfile -Command "(Invoke-WebRequest -Uri '$REPO/raw/$BRANCH/SKILL.md' -UseBasicParsing -TimeoutSec 20).Content" 2>/dev/null | grep -E '^\s+version:' | head -1 | sed -E 's/.*version:\s*"?([^"]*)"?/\1/') || true
fi

if [ -z "$REMOTE_VERSION" ]; then
  echo "错误: 无法获取远端版本，请检查网络或 LUNYU_REPO"
  exit 1
fi
echo "远端版本: $REMOTE_VERSION"

# ---------- 版本比较 ----------
if [ "$FORCE" != "1" ] && [ "$LOCAL_VERSION" = "$REMOTE_VERSION" ]; then
  echo "已是最新版本 ($LOCAL_VERSION)，无需更新。"
  exit 0
fi

if [ "$FORCE" != "1" ]; then
  echo "发现新版本: $LOCAL_VERSION -> $REMOTE_VERSION"
  read -r -p "是否现在更新？[y/N] " CONFIRM
  if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    echo "已取消更新。"
    exit 0
  fi
fi

# ---------- 下载并解压覆盖 ----------
echo "下载最新版 ..."
ZIP_URL="$REPO/archive/refs/heads/$BRANCH.zip"
if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$ZIP_URL" -o "$TMP_DIR/lunyu.zip"
else
  powershell.exe -NoProfile -Command "Invoke-WebRequest -Uri '$ZIP_URL' -OutFile '$TMP_DIR/lunyu.zip' -UseBasicParsing -TimeoutSec 60"
fi

cd "$TMP_DIR"
# 解压后目录名形如 lunyu-skill-main/
unzip -q lunyu.zip
SRC_DIR="$TMP_DIR/lunyu-skill-$BRANCH"
if [ ! -d "$SRC_DIR" ]; then
  # 兼容 repo 名不叫 lunyu-skill 的情况
  SRC_DIR=$(find "$TMP_DIR" -maxdepth 1 -type d -name "*$BRANCH" | head -1)
fi
if [ -z "$SRC_DIR" ] || [ ! -d "$SRC_DIR" ]; then
  echo "错误: 解压后未找到源码目录"
  exit 1
fi

# 备份 .lunyu 数据（如有）
if [ -d "$SKILL_DIR/.lunyu" ]; then
  cp -r "$SKILL_DIR/.lunyu" "$TMP_DIR/.lunyu.bak"
fi

# 覆盖（用 rsync 风格：先复制，再删多余）
cp -r "$SRC_DIR/." "$SKILL_DIR/"
# 清理被删除的旧文件（排除 .lunyu 和 .git）
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete --exclude '.lunyu' --exclude '.git' "$SRC_DIR/" "$SKILL_DIR/"
else
  # 无 rsync 时仅覆盖，不删除多余文件（保守）
  :
fi

# 恢复 .lunyu 数据
if [ -d "$TMP_DIR/.lunyu.bak" ]; then
  rm -rf "$SKILL_DIR/.lunyu"
  cp -r "$TMP_DIR/.lunyu.bak" "$SKILL_DIR/.lunyu"
fi

# 恢复脚本可执行权限
chmod +x "$SKILL_DIR/scripts/"*.sh 2>/dev/null || true

echo "更新完成: $LOCAL_VERSION -> $REMOTE_VERSION"
echo "当前版本: $(grep -E '^\s+version:' "$SKILL_DIR/SKILL.md" | head -1 | sed -E 's/.*version:\s*"?([^"]*)"?/\1/')"