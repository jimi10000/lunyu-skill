#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shell 脚本完整性测试

build_apk.sh / vm_test.sh / self_update.sh / github-publish.sh / daily_report.sh
不实际执行（会打网络/构建），但也不只做「文件存在」这种永远为真的检查:
- 文件存在且非空
- 可执行位（POSIX）/ bash 语法可被解析（bash -n，只解析不执行）
- 以 bash shebang 开头
- 包含关键函数/命令
- 不依赖 GNU-only 命令（sort -V 之类），或有跨平台回退
- 无硬编码 token（脱敏检查）

另外对 Python 脚本做轻量行为测试: `python xxx.py --help` 必须正常输出 usage。
"""
import os
import re
import shutil
import subprocess
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
SH_NAMES = ("build_apk.sh", "vm_test.sh", "self_update.sh",
            "github-publish.sh", "daily_report.sh")

# 这些脚本跑 --help 只打印 usage，不会触发构建/发版/联网
PY_HELP_NAMES = ("report.py", "logkit.py", "scheduler.py", "self_update.py")

HELP_TIMEOUT = 20  # 秒，防挂死


def read(name):
    with open(os.path.join(SCRIPTS, name), "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


class ShellScriptTest(unittest.TestCase):
    def test_all_exist(self):
        for name in SH_NAMES:
            path = os.path.join(SCRIPTS, name)
            self.assertTrue(os.path.isfile(path), name)
            # 空文件也算不上有内容
            self.assertGreater(os.path.getsize(path), 0, f"{name} 是空文件")
            if os.name != "nt":  # Windows 没有可执行位语义，脚本由 `bash x.sh` 调用
                self.assertTrue(os.access(path, os.X_OK), f"{name} 缺少可执行权限")

    def test_shebang(self):
        for name in SH_NAMES:
            first = read(name).splitlines()[0]
            self.assertRegex(first, r"^#!(/usr/bin/env bash|/bin/bash)\s*$",
                             f"{name} shebang 错误: {first!r}")

    def test_bash_syntax_parses(self):
        """bash -n 只做语法解析，不执行任何命令。"""
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("未找到 bash，跳过语法解析检查")
        for name in SH_NAMES:
            r = subprocess.run([bash, "-n", os.path.join(SCRIPTS, name)],
                               capture_output=True, text=True, timeout=30)
            self.assertEqual(r.returncode, 0, f"{name} 语法错误: {r.stderr.strip()}")

    def test_python_scripts_print_usage(self):
        """--help 必须真的打印 usage 并返回 0（不是空输出、不是报错退出）。"""
        for name in PY_HELP_NAMES:
            path = os.path.join(SCRIPTS, name)
            r = subprocess.run([sys.executable, path, "--help"],
                               capture_output=True, text=True, timeout=HELP_TIMEOUT)
            self.assertEqual(r.returncode, 0, f"{name} --help 退出码 {r.returncode}: {r.stderr[:200]}")
            self.assertIn("usage:", r.stdout.lower(), f"{name} --help 未输出 usage")
            self.assertGreater(len(r.stdout.strip()), 0, f"{name} --help 空输出")

    def test_build_apk_keywords(self):
        content = read("build_apk.sh")
        self.assertIn("gradlew", content)
        self.assertIn("md5", content.lower())
        self.assertIn("APK", content.upper())

    def test_vm_test_keywords(self):
        content = read("vm_test.sh")
        self.assertIn("adb", content.lower())
        self.assertIn("ANDROID_HOME", content)

    def test_self_update_keywords(self):
        content = read("self_update.sh")
        self.assertIn("curl", content)
        # 版本比较会去掉 v 前缀
        self.assertIn("sed", content)

    def test_self_update_no_gnu_only_commands(self):
        """GNU coreutils 专属命令（sort -V / grep -P / sed -r / date -d ...）
        在 macOS/BSD 上没有。用到就必须有 command -v 探测 + 跨平台回退，
        否则脚本在 macOS 上静默失败。"""
        content = read("self_update.sh")
        gnu_only = ("sort -V", "grep -P", "sed -r", "date -d", "realpath", "readlink -f")
        used = [c for c in gnu_only if c in content]
        for cmd in used:
            self.assertIn("command -v", content,
                          f"{cmd} 是 GNU-only 命令，必须做 command -v 探测并回退")

    def test_self_update_delegates_to_python(self):
        """.sh 有 Python 时必须委托 .py，避免两套更新逻辑走偏。"""
        sh = read("self_update.sh")
        self.assertIn("self_update.py", sh)
        self.assertIn("exec python", sh)

    def test_self_update_py_exists_and_cross_platform(self):
        """Python 版自更新必须存在，且不依赖 unzip/rsync/curl。"""
        py = os.path.join(SCRIPTS, "self_update.py")
        self.assertTrue(os.path.isfile(py))
        content = open(py, encoding="utf-8").read()
        self.assertIn("zipfile", content)       # 自己解压，不依赖 unzip
        self.assertNotIn("subprocess", content)  # 不调任何外部命令（不依赖 rsync/curl）
        self.assertIn("urllib.request", content)

    def test_self_update_version_reads_top_level(self):
        """版本解析必须顶层优先（技能市场只读顶层 version）。"""
        py = os.path.join(SCRIPTS, "self_update.py")
        content = open(py, encoding="utf-8").read()
        self.assertIn("^version:", content)          # 顶层优先
        self.assertIn("version:\\s*", content)       # 兼容缩进回退

    def test_github_publish_keywords(self):
        content = read("github-publish.sh")
        self.assertIn("trap", content)
        self.assertIn("cleanup", content)
        self.assertIn("git push", content)

    def test_github_publish_token_not_in_url_or_argv(self):
        """回归: PAT 不得拼进 remote URL（会明文落进 .git/config）。"""
        content = read("github-publish.sh")
        self.assertNotIn(":$TOKEN@", content)
        self.assertNotIn("${TOKEN}@", content)
        self.assertNotIn("GITHUB_TOKEN=\"$1\"", content)
        # 推送用 Authorization 请求头注入凭据，不落盘
        self.assertIn("http.extraHeader", content)
        self.assertIn("Authorization: Bearer", content)
        # 环境变量优先，stdin 兜底
        self.assertIn("GITHUB_TOKEN", content)
        self.assertIn("read -r -s", content)

    def test_github_publish_legacy_arg_still_supported_but_warned(self):
        """旧调用（PAT 作位置参数）仍可用，但必须告警引导改用环境变量。"""
        content = read("github-publish.sh")
        self.assertIn("已废弃", content)
        self.assertIn("GITHUB_PUBLISH_LEGACY_ARGS", content)

    def test_github_publish_cred_file_is_protected_and_cleaned(self):
        """临时凭据文件：600 创建、退出时 shred/rm 销毁。"""
        content = read("github-publish.sh")
        self.assertIn("chmod 600", content)
        self.assertIn("shred", content)
        self.assertIn("rm -f \"$CRED_FILE\"", content)

    def test_daily_report_keywords(self):
        content = read("daily_report.sh")
        self.assertIn("report.py", content)
        self.assertIn("daily", content)

    def test_no_hardcoded_tokens(self):
        """所有 shell 脚本不应含真实 token 形态的字符串。"""
        secret_patterns = [
            re.compile(r"\bghp_[A-Za-z0-9]{36,}\b"),
            re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
            re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        ]
        for name in ("build_apk.sh", "vm_test.sh", "self_update.sh",
                     "github-publish.sh", "daily_report.sh"):
            content = read(name)
            for pat in secret_patterns:
                self.assertIsNone(pat.search(content), f"{name} 含疑似密钥")

    def test_github_publish_no_personal_info(self):
        """github-publish.sh 应已脱敏：不含个人邮箱/用户名。"""
        content = read("github-publish.sh")
        self.assertNotIn("jimi10000", content)
        self.assertNotIn("@qq.com", content)


if __name__ == "__main__":
    unittest.main()