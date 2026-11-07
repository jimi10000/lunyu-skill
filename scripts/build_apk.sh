#!/usr/bin/env bash
# ============================================================
# build_apk.sh — 自动化打包 Android APK（Gradle）
#
# 从风火轮音乐「gradle 自动化打包」流程提炼的通用版本。
# 支持指定项目目录、模块、构建类型、架构，打包完成后输出
# APK 路径 + md5（md5 是交付铁律之一，直接生成）。
#
# 用法:
#   ./build_apk.sh [--dir <android项目目录>] [--module <模块目录>] \
#       [--flavor <flavor>] [--build-type release|debug] \
#       [--arch <abi>] [--out <输出目录>]
#
# 环境变量:
#   ANDROID_HOME   Android SDK 路径（可选，gradle 会自动找）
#
# 默认值:
#   项目目录      当前目录
#   模块          app（对应 gradle 模块 :app；多级模块传 feature/home）
#   build-type    release
#   架构          不传 -Pabi（仅当显式指定 --arch 时才传给 gradle）
#   输出目录      <项目目录>/<模块>/build/outputs/apk
#
# 退出码: 0=成功 / 1=失败
# ============================================================
set -euo pipefail

# ---------- 参数解析 ----------
PROJECT_DIR="$(pwd)"
MODULE="app"
BUILD_TYPE="release"
ARCH=""
OUT_DIR=""

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) PROJECT_DIR="$2"; shift 2 ;;
    --module) MODULE="$2"; shift 2 ;;
    --build-type) BUILD_TYPE="$2"; shift 2 ;;
    --arch) ARCH="$2"; shift 2 ;;
    --flavor) FLAVOR="$2"; shift 2 ;;
    --out) OUT_DIR="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

if [ ! -d "$PROJECT_DIR" ]; then
  echo "错误: 项目目录不存在: $PROJECT_DIR"
  exit 1
fi

GRADLEW="$PROJECT_DIR/gradlew"
if [ ! -x "$GRADLEW" ]; then
  echo "错误: 未找到 gradlew: $GRADLEW"
  exit 1
fi

# ---------- 构建 ----------
# 模块目录 -> gradle 坐标：app -> :app ; feature/home -> :feature:home
MODULE="${MODULE#:}"
MODULE_COLON=":${MODULE//\//:}"
TASK="${MODULE_COLON}:assemble${BUILD_TYPE^}"
if [ -n "${FLAVOR:-}" ]; then
  TASK="${MODULE_COLON}:assemble${FLAVOR^}${BUILD_TYPE^}"
fi
echo "=========================================="
echo "Android 自动化打包"
echo "  项目目录 : $PROJECT_DIR"
echo "  模块     : $MODULE"
echo "  Task     : $TASK"
if [ -n "$ARCH" ]; then
  echo "  架构     : $ARCH (通过 -Pabi 传入)"
fi
echo "=========================================="

cd "$PROJECT_DIR"
if [ -n "$ARCH" ]; then
  "$GRADLEW" "$TASK" -Pabi="$ARCH" --no-daemon
else
  "$GRADLEW" "$TASK" --no-daemon
fi

# ---------- 定位 APK ----------
DEFAULT_OUT_DIR="$PROJECT_DIR/$MODULE/build/outputs/apk"
if [ -z "$OUT_DIR" ]; then
  # 自动定位：release 目录
  if [ -d "$DEFAULT_OUT_DIR/release" ]; then
    OUT_DIR="$DEFAULT_OUT_DIR/release"
  elif [ -d "$DEFAULT_OUT_DIR/debug" ]; then
    OUT_DIR="$DEFAULT_OUT_DIR/debug"
  else
    OUT_DIR="$DEFAULT_OUT_DIR"
  fi
fi

# 找出最新 APK
# GNU find 支持 -printf; BSD find(macOS) 不支持, 用 ls -t 兜底
APK=""
if find "$OUT_DIR" -maxdepth 0 -printf '' >/dev/null 2>&1; then
  APK=$(find "$OUT_DIR" -name "*.apk" -type f -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2-)
else
  APK=$(ls -t "$OUT_DIR"/*.apk "$OUT_DIR"/*/*.apk 2>/dev/null | head -1)
fi
if [ -z "$APK" ]; then
  echo "错误: 未在 $OUT_DIR 找到 APK 文件"
  exit 1
fi

echo "APK: $APK"
# md5 兼容 Linux(md5sum) / macOS(md5 -q) / Windows Git Bash(md5sum)
if command -v md5sum >/dev/null 2>&1; then
  APK_MD5=$(md5sum "$APK" | awk '{print $1}')
elif command -v md5 >/dev/null 2>&1; then
  APK_MD5=$(md5 -q "$APK")
else
  APK_MD5="(md5 工具不可用)"
fi
echo "MD5: $APK_MD5"
echo "BUILD_DONE"