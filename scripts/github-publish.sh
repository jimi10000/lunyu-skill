#!/usr/bin/env bash
# ============================================================
# github-publish.sh - 自动建仓库并推送项目
#
# 用法（推荐，PAT 不进命令行）:
#   GITHUB_TOKEN=<PAT> ./github-publish.sh <repo_name> <项目目录> [描述] [public|private]
#   printf '%s' "$TOKEN" | ./github-publish.sh <repo_name> <项目目录> [描述] [public|private]
#   ./github-publish.sh <repo_name> <项目目录>        # 交互式从 stdin 读，不回显
#
# 旧用法（已废弃，仅兼容老调用，会打印弃用告警）:
#   ./github-publish.sh <PAT> <repo_name> <项目目录> [描述] [public|private]
#
# 功能:
#   1. 用 PAT 创建 GitHub 仓库 (REST API)
#   2. 初始化本地 git 并推送 main
#   3. 设置仓库描述
#   4. 输出仓库地址
#
# 凭据安全约定（本次修复重点，改动前请看这里）:
#   1. PAT 默认不再作为位置参数传入 —— 命令行参数会落进 shell history，
#      且能被 ps aux 看到。优先级: GITHUB_TOKEN 环境变量 > stdin(read -s 不回显)
#      > 旧式位置参数（仅兼容，会告警引导改用环境变量）。
#   2. 推送不使用 https://user:TOKEN@github.com/... 这种 URL。
#      原因: git 会把 remote URL 持久化写进 .git/config —— 凭据明文落盘，
#      且脚本被 Ctrl-C / 异常中断时 trap 还没来得及清理就已经留下了。
#      改为在单次 git 调用期间注入 Authorization 请求头:
#        git >= 2.31: 走 GIT_CONFIG_COUNT/GIT_CONFIG_KEY_0/GIT_CONFIG_VALUE_0
#                     环境变量注入 http.extraHeader，PAT 连命令行参数里都不出现
#        更老的 git : 退化为 -c http.extraHeader=... （同样不写 .git/config）
#      两种方式都不碰 remote URL，退出后 .git/config 里没有任何凭据。
#   3. trap cleanup EXIT 负责销毁临时凭据文件（600 权限，shred 优先，无则 rm）
#      并把 remote URL 归一化回无凭据形式。
#
# 依赖:
#   - git
#   - PowerShell (Invoke-RestMethod)
#   - 有 repo 权限的 GitHub Personal Access Token
# ============================================================
set -euo pipefail

usage() {
  cat <<EOF
用法:
  GITHUB_TOKEN=<PAT> $0 <repo_name> <项目目录> [描述] [public|private]
  printf '%s' "\$TOKEN" | $0 <repo_name> <项目目录> [描述] [public|private]

PAT 请通过 GITHUB_TOKEN 环境变量或 stdin 传入；
位置参数传 PAT 已废弃（仍兼容，但会把凭据暴露进 history/ps）。
EOF
}

# GitHub 用户名：可用环境变量覆盖，避免硬编码个人账号
GITHUB_USER="${GITHUB_USER:-your-github-username}"

CRED_FILE=""

# 退出钩子：销毁临时凭据 + 清掉 URL 里可能残留的凭据
cleanup() {
  if [ -n "$CRED_FILE" ] && [ -f "$CRED_FILE" ]; then
    if command -v shred >/dev/null 2>&1; then
      shred -u "$CRED_FILE" 2>/dev/null || rm -f "$CRED_FILE"
    else
      rm -f "$CRED_FILE"
    fi
  fi
  # remote URL 归一化：即便旧版本遗留过 user:token@ 形式的 URL，也会被覆盖掉
  git remote set-url origin "https://github.com/${GITHUB_USER}/${REPO:-}.git" 2>/dev/null || true
  return 0
}

# ---------- 0. 参数解析 ----------
# PAT 形态: 经典 ghp_/gho_/ghu_/ghs_/ghr_ 或细粒度 github_pat_
TOKEN_RE='^(gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,})$'

LEGACY_TOKEN_ARG=0
if [ "${GITHUB_PUBLISH_LEGACY_ARGS:-0}" = "1" ]; then
  LEGACY_TOKEN_ARG=1
elif [ "${1:-}" ] && [[ "$1" =~ $TOKEN_RE ]]; then
  LEGACY_TOKEN_ARG=1
fi

TOKEN=""
if [ "$LEGACY_TOKEN_ARG" -eq 1 ]; then
  if [ $# -lt 3 ]; then
    echo "用法: $0 <PAT> <repo_name> <项目目录> [描述] [public|private]" >&2
    exit 1
  fi
  TOKEN="$1"
  shift
  echo "警告: 通过命令行参数传递 PAT 已废弃 —— 会进 shell history 且 ps aux 可见。" >&2
  echo "       请改用: GITHUB_TOKEN=<PAT> $0 <repo_name> <项目目录> ..." >&2
fi

if [ $# -lt 2 ]; then
  usage >&2
  exit 1
fi

REPO="$1"
PROJECT_DIR="$2"
DESC="${3:-}"
VISIBILITY="${4:-public}"   # 默认 public
if [ "$VISIBILITY" = "private" ]; then
  VIS_BOOL="True"
else
  VIS_BOOL="False"
fi

# ---------- 1. 取 PAT：环境变量 > stdin ----------
if [ -z "$TOKEN" ]; then
  TOKEN="${GITHUB_TOKEN:-}"
fi
if [ -z "$TOKEN" ]; then
  # 从 stdin 读，read -s 关闭回显；管道和交互式都适用
  if [ -t 0 ]; then
    printf '请输入 GitHub PAT（不回显）: ' >&2
  fi
  IFS= read -r -s TOKEN || true
  if [ -t 0 ]; then
    printf '\n' >&2
  fi
fi
if [ -z "$TOKEN" ]; then
  echo "错误: 未提供 PAT。请设置环境变量 GITHUB_TOKEN，或通过 stdin 传入。" >&2
  usage >&2
  exit 1
fi

# 校验目录
if [ ! -d "$PROJECT_DIR" ]; then
  echo "错误: 项目目录不存在: $PROJECT_DIR"
  exit 1
fi

# 临时凭据文件：600 权限，退出即销毁。
# git 的 Authorization 头从这里取值，避免 PAT 常驻在 shell 变量里被意外 echo。
CRED_FILE="$(mktemp "${TMPDIR:-/tmp}/ghpub.XXXXXX")" || {
  echo "错误: 无法创建临时凭据文件" >&2
  exit 1
}
chmod 600 "$CRED_FILE"
printf '%s' "$TOKEN" > "$CRED_FILE"
trap cleanup EXIT INT TERM

echo "=========================================="
echo "GitHub 自动发布"
echo "  仓库名   : $REPO"
echo "  可见性   : $VISIBILITY"
echo "  项目目录 : $PROJECT_DIR"
echo "  描述     : ${DESC:-无}"
echo "=========================================="

# PAT 传给子进程只通过环境变量前缀（不进 powershell 的命令行参数）
# ---------- 2. 创建远程仓库 ----------
echo "[1/4] 创建 GitHub 仓库: $REPO ..."
CREATE_BODY=$(python -c "
import json,sys
body = {
  'name': '$REPO',
  'description': '$DESC',
  'private': $VIS_BOOL,
  'auto_init': False,
}
print(json.dumps(body, ensure_ascii=False))
")
CREATE_JSON=$(GITHUB_TOKEN="$(cat "$CRED_FILE")" powershell.exe -NoProfile -Command "
\$h = @{ Authorization = \"Bearer \$env:GITHUB_TOKEN\"; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
try {
  Invoke-RestMethod -Uri 'https://api.github.com/user/repos' -Method Post -Headers \$h -Body '$CREATE_BODY' -ContentType 'application/json' -TimeoutSec 30 | ConvertTo-Json -Compress
} catch {
  \$code = \$_.Exception.Response.StatusCode.value__
  Write-Output \"ERROR:\$code\"
  exit 1
}
" 2>/dev/null)

if echo "$CREATE_JSON" | grep -q "ERROR:"; then
  echo "创建仓库失败: $CREATE_JSON"
  exit 1
fi
echo "  仓库创建成功: https://github.com/$GITHUB_USER/$REPO"

# ---------- 3. 初始化本地 git 并推送 ----------
echo "[2/4] 初始化本地 git ..."
cd "$PROJECT_DIR"

# 清理旧 remote
git remote remove origin 2>/dev/null || true

# 如果还没有 main 分支，创建
if ! git rev-parse --verify main >/dev/null 2>&1; then
  if [ -z "$(git branch --show-current 2>/dev/null)" ]; then
    git init -b main 2>/dev/null || { git init && git checkout -b main; }
  else
    git branch -M main
  fi
fi

# 配置身份（如未设置，用环境变量或 GitHub 用户名占位）
# 安全提醒：请把 GIT_USER_NAME / GIT_USER_EMAIL 设成你自己的，不要硬编码真实账号
GIT_USER_NAME="${GIT_USER_NAME:-$(whoami)}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-user@example.com}"
if [ -z "$(git config user.name 2>/dev/null)" ]; then
  git config user.name "$GIT_USER_NAME"
fi
if [ -z "$(git config user.email 2>/dev/null)" ]; then
  git config user.email "$GIT_USER_EMAIL"
fi

# 提交（如未提交）
if [ -z "$(git log --oneline -1 2>/dev/null)" ]; then
  git add -A
  git commit -m "feat: 初始化 $REPO" 2>/dev/null || echo "  无文件可提交"
fi

# remote URL 里绝不带凭据（否则会写进 .git/config）
git remote add origin "https://github.com/$GITHUB_USER/$REPO.git" 2>/dev/null || \
  git remote set-url origin "https://github.com/$GITHUB_USER/$REPO.git"

# 判断 git 是否支持用环境变量注入配置（>= 2.31），支持则 PAT 完全不进命令行
USE_ENV_CONFIG=0
GIT_VER="$(git --version 2>/dev/null | sed -E 's/[^0-9]*([0-9]+)\.([0-9]+).*/\1 \2/' || true)"
if [ -n "$GIT_VER" ]; then
  GIT_MAJOR="${GIT_VER%% *}"
  GIT_MINOR="${GIT_VER##* }"
  if [ "${GIT_MAJOR:-0}" -gt 2 ] 2>/dev/null || \
     { [ "${GIT_MAJOR:-0}" -eq 2 ] && [ "${GIT_MINOR:-0}" -ge 31 ]; }; then
    USE_ENV_CONFIG=1
  fi
fi

PUSH_TOKEN="$(cat "$CRED_FILE")"

echo "  推送 main ..."
if [ "$USE_ENV_CONFIG" -eq 1 ]; then
  # PAT 只存在于 git 进程的环境变量里：不落盘、不进 URL、不进 argv
  GIT_CONFIG_COUNT=1 \
  GIT_CONFIG_KEY_0="http.extraHeader" \
  GIT_CONFIG_VALUE_0="Authorization: Bearer $PUSH_TOKEN" \
  GIT_TERMINAL_PROMPT=0 \
    git push -u origin main 2>&1 | tail -3
else
  # 老版本 git 的退化路径：单次调用注入请求头，同样不写 .git/config
  GIT_TERMINAL_PROMPT=0 \
    git -c "http.extraHeader=Authorization: Bearer $PUSH_TOKEN" push -u origin main 2>&1 | tail -3
fi
echo "  推送成功"

# ---------- 4. 设置仓库描述（幂等） ----------
if [ -n "$DESC" ]; then
  echo "[3/4] 更新仓库描述 ..."
  UPDATE_BODY=$(python -c "
import json
print(json.dumps({'description': '$DESC'}, ensure_ascii=False))
")
  GITHUB_TOKEN="$(cat "$CRED_FILE")" powershell.exe -NoProfile -Command "
\$h = @{ Authorization = \"Bearer \$env:GITHUB_TOKEN\"; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
try {
  Invoke-RestMethod -Uri 'https://api.github.com/repos/$GITHUB_USER/$REPO' -Method Patch -Headers \$h -Body '$UPDATE_BODY' -ContentType 'application/json' -TimeoutSec 30 | Out-Null
} catch {
  Write-Output '  描述更新失败(不影响发布)'
}
" 2>/dev/null
fi

# ---------- 5. 输出结果 ----------
echo "[4/4] 完成!"
echo "=========================================="
echo "  仓库地址: https://github.com/$GITHUB_USER/$REPO"
echo "  克隆命令: git clone https://github.com/$GITHUB_USER/$REPO.git"
echo "=========================================="
