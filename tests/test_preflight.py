#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""preflight.py 单元测试

验证:
- 密钥扫描: AWS AK / 私钥 / GitHub Token / 占位符豁免 / allowlist 豁免
- 大文件警告
- 调试残留检测
- .gitignore 检查
- 项目类型识别
- Report 数据结构
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import preflight


class ReportTest(unittest.TestCase):
    def test_report(self):
        rep = preflight.Report()
        rep.block("b1")
        rep.warn("w1")
        rep.info("i1")
        self.assertEqual(rep.blockers, ["b1"])
        self.assertEqual(rep.warnings, ["w1"])
        self.assertEqual(rep.infos, ["i1"])


class SecretScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def write(self, rel, content):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_aws_key_blocked(self):
        self.write("config.py", "aws_key = 'AKIAIOSFODNN7EXAMPLE'\n")
        rep = preflight.Report()
        hits = preflight.scan_secrets(self.tmp, rep)
        self.assertGreater(hits, 0)
        self.assertTrue(any("AWS Access Key" in b for b in rep.blockers))

    def test_private_key_blocked(self):
        self.write("key.py", "-----BEGIN RSA PRIVATE KEY-----\nMIIE\n")
        rep = preflight.Report()
        hits = preflight.scan_secrets(self.tmp, rep)
        self.assertGreater(hits, 0)

    def test_github_token_blocked(self):
        self.write("ci.sh", "export GH_TOKEN=ghp_" + "A" * 36 + "\n")
        rep = preflight.Report()
        hits = preflight.scan_secrets(self.tmp, rep)
        self.assertGreater(hits, 0)

    def test_placeholder_not_blocked(self):
        self.write("config.py", "password = 'xxxxxx'\n")
        rep = preflight.Report()
        hits = preflight.scan_secrets(self.tmp, rep)
        self.assertEqual(hits, 0)

    def test_allowlist_exempt(self):
        self.write("config.py", "password = 'xxxxxxxx'  # allowlist secret\n")
        rep = preflight.Report()
        hits = preflight.scan_secrets(self.tmp, rep)
        self.assertEqual(hits, 0)

    def test_binary_skipped(self):
        self.write("img.png", "AKIAIOSFODNN7EXAMPLE")
        rep = preflight.Report()
        hits = preflight.scan_secrets(self.tmp, rep)
        self.assertEqual(hits, 0)


class LargeFileTest(unittest.TestCase):
    def test_large_file_warns(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "big.dat"), "wb") as f:
            f.write(b"0" * int(1.5 * 1024 * 1024))
        rep = preflight.Report()
        preflight.scan_large_files(tmp, rep)
        self.assertEqual(len(rep.warnings), 1)
        self.assertIn("大文件", rep.warnings[0])


class DebugScanTest(unittest.TestCase):
    def test_console_log_found(self):
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "src"), exist_ok=True)
        with open(os.path.join(tmp, "src", "a.js"), "w", encoding="utf-8") as f:
            f.write("console.log('x')\n")
        rep = preflight.Report()
        total = preflight.scan_debug(tmp, rep)
        self.assertGreater(total, 0)
        self.assertTrue(any("调试残留" in w for w in rep.warnings))

    def test_scripts_dir_ignored(self):
        tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(tmp, "scripts"), exist_ok=True)
        with open(os.path.join(tmp, "scripts", "a.py"), "w", encoding="utf-8") as f:
            f.write("print('x')\n")
        rep = preflight.Report()
        total = preflight.scan_debug(tmp, rep)
        self.assertEqual(total, 0)


class GitignoreTest(unittest.TestCase):
    def test_missing_gitignore_warns(self):
        tmp = tempfile.mkdtemp()
        rep = preflight.Report()
        preflight.scan_gitignore(tmp, rep)
        self.assertEqual(len(rep.warnings), 1)
        self.assertIn(".gitignore", rep.warnings[0])

    def test_complete_gitignore_no_warn(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, ".gitignore"), "w", encoding="utf-8") as f:
            f.write(".env\nnode_modules\n.venv\n__pycache__\ndist\nbuild\n*.log\n")
        rep = preflight.Report()
        preflight.scan_gitignore(tmp, rep)
        self.assertEqual(len(rep.warnings), 0)


class DetectProjectTest(unittest.TestCase):
    def test_node(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"scripts": {"lint": "eslint .", "test": "jest"}}, f)
        lang, lint, typ, test = preflight.detect_project(tmp)
        self.assertEqual(lang, "Node")
        self.assertEqual(lint, "npm run lint")
        self.assertEqual(test, "npm test")

    def test_python(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "requirements.txt"), "w", encoding="utf-8") as f:
            f.write("requests\n")
        lang, _, _, _ = preflight.detect_project(tmp)
        self.assertEqual(lang, "Python")

    def test_none(self):
        tmp = tempfile.mkdtemp()
        lang, _, _, _ = preflight.detect_project(tmp)
        self.assertIsNone(lang)

    def test_pyproject_ruff(self):
        tmp = tempfile.mkdtemp()
        with open(os.path.join(tmp, "pyproject.toml"), "w", encoding="utf-8") as f:
            f.write("[tool.ruff]\n")
        lang, lint, _, _ = preflight.detect_project(tmp)
        self.assertEqual(lang, "Python")
        self.assertEqual(lint, "ruff check .")


class RunGatesTest(unittest.TestCase):
    def test_skip_when_no_cmd(self):
        rep = preflight.Report()
        preflight.run_gates(".", rep, "Node", None, None, None)
        self.assertTrue(any("跳过" in i for i in rep.infos))

    def test_cmd_127_skipped(self):
        rep = preflight.Report()
        with unittest.mock.patch.object(preflight, "run_cmd", return_value=(127, "not found")):
            preflight.run_gates(".", rep, "Node", "npm run lint", None, None)
        self.assertTrue(any("命令不可用" in i for i in rep.infos))

    def test_cmd_fail_blocked(self):
        rep = preflight.Report()
        with unittest.mock.patch.object(preflight, "run_cmd", return_value=(1, "boom")):
            preflight.run_gates(".", rep, "Node", "npm test", None, None)
        self.assertTrue(any("失败" in b for b in rep.blockers))


if __name__ == "__main__":
    unittest.main()