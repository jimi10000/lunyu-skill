#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shell 脚本完整性测试

build_apk.sh / vm_test.sh / self_update.sh / github-publish.sh / daily_report.sh
不实际执行（会打网络/构建），只做静态完整性检查:
- 文件存在
- 以 bash shebang 开头
- 包含关键函数/命令
- 无硬编码 token（脱敏检查）
"""
import os
import re
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")


def read(name):
    with open(os.path.join(SCRIPTS, name), "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


class ShellScriptTest(unittest.TestCase):
    def test_all_exist(self):
        for name in ("build_apk.sh", "vm_test.sh", "self_update.sh",
                     "github-publish.sh", "daily_report.sh"):
            self.assertTrue(os.path.isfile(os.path.join(SCRIPTS, name)), name)

    def test_shebang(self):
        for name in ("build_apk.sh", "vm_test.sh", "self_update.sh",
                     "github-publish.sh", "daily_report.sh"):
            content = read(name)
            self.assertTrue(content.startswith("#!/usr/bin/env bash") or content.startswith("#!/bin/bash"),
                            f"{name} shebang 错误: {content[:50]!r}")

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
        self.assertIn("sort -V", content)
        self.assertIn("curl", content)
        # 版本比较会去掉 v 前缀
        self.assertIn("sed", content)

    def test_github_publish_keywords(self):
        content = read("github-publish.sh")
        self.assertIn("trap", content)
        self.assertIn("cleanup", content)
        self.assertIn("git push", content)

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