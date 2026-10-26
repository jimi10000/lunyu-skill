#!/usr/bin/env bash
# ============================================================
# vm_test.sh — Android 模拟器自动化冒烟测试
#
# 从风火轮音乐「AAOS 模拟器实测 APK」流程提炼的通用版本：
# 启动模拟器 → 等待开机 → 安装 APK → 拉起主 Activity →
# 截图 + UI dump + 抓 logcat 崩溃日志，一条龙输出测试报告。
#
# 用法:
#   ./vm_test.sh <apk路径> <应用包名> [输出目录]
#
# 环境变量:
#   ANDROID_HOME    Android SDK 路径（默认 C:\\AndroidSDK）
#   AVD_NAME        模拟器 AVD 名称（默认 fhw_test）
#   EXTRA_LOGCAT    额外的 logcat 过滤关键词（逗号分隔，可选）
#
# 输出:
#   指定目录下生成 vm_test.log / shot_launch.png / ui_dump.xml
#
# 退出码: 0=通过 / 1=失败
# ============================================================
set -uo pipefail

if [ $# -lt 2 ]; then
  echo "用法: $0 <apk路径> <应用包名> [输出目录]"
  exit 1
fi

APK="$1"
PACKAGE="$2"
OUT_DIR="${3:-$(pwd)}"

export ANDROID_HOME="${ANDROID_HOME:-'C:\AndroidSDK'}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
ADB="$ANDROID_HOME/platform-tools/adb.exe"
EMU="$ANDROID_HOME/emulator/emulator.exe"
AVD_NAME="${AVD_NAME:-fhw_test}"
LOG="$OUT_DIR/vm_test.log"

mkdir -p "$OUT_DIR"
: > "$LOG"

if [ ! -f "$APK" ]; then
  echo "错误: APK 不存在: $APK" | tee -a "$LOG"
  exit 1
fi
if [ ! -x "$ADB" ] || [ ! -x "$EMU" ]; then
  echo "错误: 未找到 adb/emulator，请检查 ANDROID_HOME" | tee -a "$LOG"
  exit 1
fi

echo "[$(date +%T)] launch emulator ($AVD_NAME) ..." | tee -a "$LOG"
"$EMU" -avd "$AVD_NAME" -no-snapshot -wipe-data -accel off -no-audio -gpu swiftshader -no-window >> "$LOG" 2>&1 &
EMU_PID=$!
echo "[$(date +%T)] emulator pid=$EMU_PID" | tee -a "$LOG"

"$ADB" wait-for-device
echo "[$(date +%T)] adb device connected" | tee -a "$LOG"

for i in $(seq 1 120); do
  b=$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
  if [ "$b" = "1" ]; then
    echo "[$(date +%T)] BOOT_COMPLETED after $((i*5))s" | tee -a "$LOG"
    break
  fi
  sleep 5
done

echo "[$(date +%T)] install APK ..." | tee -a "$LOG"
"$ADB" install -r "$APK" 2>&1 | tee -a "$LOG"
echo "[$(date +%T)] install rc=${PIPESTATUS[0]}" | tee -a "$LOG"

ACT=$("$ADB" shell cmd package resolve-activity --brief "$PACKAGE" 2>/dev/null | tail -1 | tr -d '\r')
echo "[$(date +%T)] launcher=$ACT" | tee -a "$LOG"
if [ -n "$ACT" ] && [ "$ACT" != "Priority" ]; then
  "$ADB" shell am start -n "$ACT" 2>&1 | tee -a "$LOG"
  sleep 10
  "$ADB" exec-out screencap -p > "$OUT_DIR/shot_launch.png" 2>/dev/null
  echo "[$(date +%T)] launch screenshot saved" | tee -a "$LOG"
  "$ADB" exec-out uiautomator dump /dev/tty 2>/dev/null > "$OUT_DIR/ui_dump.xml" 2>/dev/null
  echo "[$(date +%T)] ui dump bytes=$(wc -c < "$OUT_DIR/ui_dump.xml" 2>/dev/null || echo 0)" | tee -a "$LOG"
else
  echo "[$(date +%T)] 警告: 未解析到 launcher Activity，跳过启动验证" | tee -a "$LOG"
fi

echo "[$(date +%T)] logcat (crash/$PACKAGE) ===" | tee -a "$LOG"
EXTRA="${EXTRA_LOGCAT:-}"
FILTERS="FATAL|crash|AndroidRuntime|$PACKAGE"
[ -n "$EXTRA" ] && FILTERS="$FILTERS|$EXTRA"
"$ADB" logcat -d 2>/dev/null | grep -iE "$FILTERS" | tail -40 | tee -a "$LOG"

echo "[$(date +%T)] TEST_STAGE1_DONE" | tee -a "$LOG"
# 无崩溃关键字则视为通过
if grep -qiE "FATAL EXCEPTION|Process: $PACKAGE.*FATAL|AndroidRuntime.*FATAL" "$LOG"; then
  echo "VM_TEST_RESULT=FAIL"
  exit 1
else
  echo "VM_TEST_RESULT=PASS"
  exit 0
fi