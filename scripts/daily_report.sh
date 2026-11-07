#!/usr/bin/env bash
# ============================================================
# daily_report.sh — 自动生成今日日报（供定时任务调用）
#
# 由 scheduler.py 注册的系统计划任务每天调用，自动汇总
# 今日缺陷/版本/CHANGELOG 生成日报到 .lunyu/reports/。
#
# 用法:
#   ./scripts/daily_report.sh [项目目录] [作者]
#
# 默认项目目录 = 当前目录；默认作者 = 空
# 项目目录必须是 git 仓库根（或含 .lunyu/ 的目录）
#
# 退出码: 0=成功 / 1=失败
# ============================================================
set -euo pipefail

PROJECT_DIR="${1:-$(pwd)}"
AUTHOR="${2:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_PY="$SCRIPT_DIR/report.py"

if [ ! -f "$REPORT_PY" ]; then
  echo "错误: 未找到 report.py: $REPORT_PY"
  exit 1
fi
if [ ! -d "$PROJECT_DIR" ]; then
  echo "错误: 项目目录不存在: $PROJECT_DIR"
  exit 1
fi

cd "$PROJECT_DIR"
# 兼容 python/python3: 新版 Ubuntu 只有 python3, Windows Git Bash 只有 python
PY=python
command -v python >/dev/null 2>&1 || PY=python3
# 如果没有 .lunyu 数据，report.py 会生成空骨架日报（不报错）
"$PY" "$REPORT_PY" daily --project "$(basename "$PROJECT_DIR")" --author "$AUTHOR" \
  --body "（自动生成日报，请补充今日完成事项）"

echo "DAILY_REPORT_DONE"