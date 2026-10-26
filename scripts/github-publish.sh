#!/usr/bin/env bash
# ============================================================
# github-publish.sh - 自动建仓库并推送项目
#
# 用法:
#   ./github-publish.sh <token> <repo_name> <项目目录> [描述] [是否公开]
#
# 示例:
#   ./github-publish.sh ghp_xxx lunyu ./lunyu "企业级研发流水线" public
#
# 功能:
#   1. 用 PAT 创建 GitHub 仓库 (REST API)
#   2. 初始化本地 git 并推送 main
#   3. 设置仓库描述
#   4. 输出仓库地址
#
# 依赖:
#   - git
#   - PowerShell (Invoke-RestMethod)
#   - 有 repo 权限的 GitHub Personal Access Token
# ============================================================
set -euo pipefail

if [ $# -lt 3 ]; then
  echo "用法: $0 <token> <repo_name> <项目目录> [描述] [public|private]"
  echo "示例: $0 ghp_xxx lunyu ./lunyu \"企业级研发流水线\" public"
  exit 1
fi

TOKEN="$1"
REPO="$2"
PROJECT_DIR="$3"
DESC="${4:-}"
VISIBILITY="${5:-public}"   # 默认 public
# GitHub 用户名：可用环境变量覆盖，避免硬编码个人账号
GITHUB_USER="${GITHUB_USER:-your-github-username}"
if [ "$VISIBILITY" = "private" ]; then
  VIS_BOOL="True"
else
  VIS_BOOL="False"
fi

# 校验目录
if [ ! -d "$PROJECT_DIR" ]; then
  echo "错误: 项目目录不存在: $PROJECT_DIR"
  exit 1
fi

echo "=========================================="
echo "GitHub 自动发布"
echo "  仓库名   : $REPO"
echo "  可见性   : $VISIBILITY"
echo "  项目目录 : $PROJECT_DIR"
echo "  描述     : ${DESC:-无}"
echo "=========================================="

# ---------- 1. 创建远程仓库 ----------
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
CREATE_JSON=$(powershell.exe -NoProfile -Command "
\$h = @{ Authorization = 'Bearer $TOKEN'; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
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

# ---------- 2. 初始化本地 git 并推送 ----------
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

# 推送
git remote add origin "https://$GITHUB_USER:$TOKEN@github.com/$GITHUB_USER/$REPO.git" 2>/dev/null || \
  git remote set-url origin "https://$GITHUB_USER:$TOKEN@github.com/$GITHUB_USER/$REPO.git"
# 无论推送成败，退出前必须清掉 remote URL 里的 token
cleanup() { git remote set-url origin "https://github.com/$GITHUB_USER/$REPO.git" 2>/dev/null || true; }
trap cleanup EXIT
git push -u origin main 2>&1 | tail -3
echo "  推送成功"

# ---------- 3. 设置仓库描述（幂等） ----------
if [ -n "$DESC" ]; then
  echo "[3/4] 更新仓库描述 ..."
  UPDATE_BODY=$(python -c "
import json
print(json.dumps({'description': '$DESC'}, ensure_ascii=False))
")
  powershell.exe -NoProfile -Command "
\$h = @{ Authorization = 'Bearer $TOKEN'; Accept = 'application/vnd.github+json'; 'X-GitHub-Api-Version' = '2022-11-28' }
try {
  Invoke-RestMethod -Uri 'https://api.github.com/repos/$GITHUB_USER/$REPO' -Method Patch -Headers \$h -Body '$UPDATE_BODY' -ContentType 'application/json' -TimeoutSec 30 | Out-Null
} catch {
  Write-Output '  描述更新失败(不影响发布)'
}
" 2>/dev/null
fi

# ---------- 4. 输出结果 ----------
echo "[4/4] 完成!"
echo "=========================================="
echo "  仓库地址: https://github.com/$GITHUB_USER/$REPO"
echo "  克隆命令: git clone https://github.com/$GITHUB_USER/$REPO.git"
echo "=========================================="