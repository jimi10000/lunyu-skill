#!/usr/bin/env bash
# ============================================================
# self_update.sh — 一键自更新 lunyu 技能包
#
# 已安装用户运行本脚本，自动从 GitHub 拉取最新版并覆盖本地技能目录。
# 适用于「zip 安装包解压安装」的用户（目录里没有 .git，git pull 不可用），
# git clone 安装的用户同样可用。
#
# 用法:
#   ./scripts/self_update.sh [--check] [--yes] [--force]
#
# 行为:
#   1. 若本机有 Python，直接委托给 scripts/self_update.py（逻辑唯一，跨平台最稳）
#   2. 无 Python 时走纯 bash 兜底：curl 下载 zip + unzip 覆盖（保留 .lunyu 数据）
#
# 退出码: 0=已是最新或更新成功 / 1=失败 / 2=有新版本(--check)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ---------- 优先委托给 Python 版（逻辑唯一，避免两套实现走偏） ----------
if command -v python >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/self_update.py" ]; then
  exec python "$SCRIPT_DIR/self_update.py" "$@"
fi
if command -v python3 >/dev/null 2>&1 && [ -f "$SCRIPT_DIR/self_update.py" ]; then
  exec python3 "$SCRIPT_DIR/self_update.py" "$@"
fi

# ===================== 以下为无 Python 环境的纯 bash 兜底 =====================
REPO="${LUNYU_REPO:-https://github.com/jimi10000/lunyu-skill}"
BRANCH="${LUNYU_BRANCH:-main}"
FORCE="${LUNYU_FORCE:-0}"

echo "技能目录: $SKILL_DIR"

# ---------- 版本号解析（POSIX 安全正则，不用 \s） ----------
# 优先级：frontmatter 顶层 version:  >  缩进的 metadata.version
# 注意：技能市场解析器只读顶层，本地也必须以顶层为准；
#       旧包可能只写在 metadata 子层，故保留回退。
extract_version() {
  local v
  v=$(grep -E '^version:[[:space:]]*"?[0-9]' 2>/dev/null | head -1 \
      | sed -E 's/^version:[[:space:]]*"?([^"]*)"?.*/\1/')
  if [ -z "$v" ]; then
    v=$(grep -E '^[[:space:]]+version:[[:space:]]*"?[0-9]' 2>/dev/null | head -1 \
        | sed -E 's/.*version:[[:space:]]*"?([^"]*)"?.*/\1/')
  fi
  printf '%s' "$v"
}

LOCAL_VERSION=""
if [ -f "$SKILL_DIR/SKILL.md" ]; then
  LOCAL_VERSION=$(extract_version < "$SKILL_DIR/SKILL.md")
fi
[ -z "$LOCAL_VERSION" ] && LOCAL_VERSION="0.0.0"
echo "本地版本: $LOCAL_VERSION"

# ---------- 拉取远端版本 ----------
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "检查远端版本 ..."
REMOTE_VERSION=""
if command -v curl >/dev/null 2>&1; then
  REMOTE_VERSION=$(curl -fsSL "$REPO/raw/$BRANCH/SKILL.md" 2>/dev/null | extract_version) || true
fi
if [ -z "$REMOTE_VERSION" ] && command -v powershell.exe >/dev/null 2>&1; then
  REMOTE_VERSION=$(powershell.exe -NoProfile -Command "(Invoke-WebRequest -Uri '$REPO/raw/$BRANCH/SKILL.md' -UseBasicParsing -TimeoutSec 20).Content" 2>/dev/null | extract_version) || true
fi

if [ -z "$REMOTE_VERSION" ]; then
  echo "错误: 无法获取远端版本，请检查网络或 LUNYU_REPO"
  exit 1
fi
echo "远端版本: $REMOTE_VERSION"

# ---------- 版本比较 ----------
# 归一化：去掉可能的 v 前缀，避免 "v1.1.0" 与 "1.1.0" 被 sort -V 误判
norm() { printf '%s' "${1#v}"; }
LOCAL_NORM="$(norm "$LOCAL_VERSION")"
REMOTE_NORM="$(norm "$REMOTE_VERSION")"

NEWER=$(printf '%s\n%s\n' "$REMOTE_NORM" "$LOCAL_NORM" | sort -V | head -1)
if [ "$FORCE" != "1" ] && [ "$NEWER" = "$REMOTE_NORM" ]; then
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
unzip -q lunyu.zip
SRC_DIR="$TMP_DIR/lunyu-skill-$BRANCH"
if [ ! -d "$SRC_DIR" ]; then
  # 兼容 repo 名不叫 lunyu-skill 的情况
  SRC_DIR=$(find "$TMP_DIR" -maxdepth 2 -type f -name SKILL.md -exec dirname {} \; | head -1)
fi
if [ -z "$SRC_DIR" ] || [ ! -d "$SRC_DIR" ]; then
  echo "错误: 解压后未找到源码目录"
  exit 1
fi

# 备份 .lunyu 数据（如有）
if [ -d "$SKILL_DIR/.lunyu" ]; then
  cp -r "$SKILL_DIR/.lunyu" "$TMP_DIR/.lunyu.bak"
fi

# 覆盖
cp -r "$SRC_DIR/." "$SKILL_DIR/"

# 恢复 .lunyu 数据
if [ -d "$TMP_DIR/.lunyu.bak" ]; then
  rm -rf "$SKILL_DIR/.lunyu"
  cp -r "$TMP_DIR/.lunyu.bak" "$SKILL_DIR/.lunyu"
fi

# 恢复脚本可执行权限
chmod +x "$SKILL_DIR/scripts/"*.sh 2>/dev/null || true

echo "更新完成: $LOCAL_VERSION -> $REMOTE_VERSION"
echo "当前版本: $(extract_version < "$SKILL_DIR/SKILL.md")"
echo "提示: 未安装 rsync/python，旧版本遗留的多余文件未自动清理；"
echo "      如需彻底同步，建议手动下载 zip 全新解压安装。"
