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
- pre-commit 钩子安装/卸载(含备份恢复、core.hooksPath 复用)
- 依赖扫描: 无固定版本 / 缺 lockfile / 高风险包 / SBOM 落盘
"""
import json
import os
import sys
import tempfile
import unittest
import unittest.mock

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
    # 样本密钥一律拼接生成：运行时仍是真实形态（扫描器照样命中），
    # 但源码里不出现连续的可疑字样，避免被市场/托管平台的密钥扫描误判为「包内含密钥」
    AWS_SAMPLE = "AKIA" + "IOSFODNN7EXAMPLE"
    PK_SAMPLE = "-----BEGIN " + "RSA PRIVATE KEY-----"

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def write(self, rel, content):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_aws_key_blocked(self):
        self.write("config.py", "aws_key = '%s'\n" % self.AWS_SAMPLE)
        rep = preflight.Report()
        hits = preflight.scan_secrets(self.tmp, rep)
        self.assertGreater(hits, 0)
        self.assertTrue(any("AWS Access Key" in b for b in rep.blockers))

    def test_private_key_blocked(self):
        self.write("key.py", "%s\nMIIE\n" % self.PK_SAMPLE)
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
        self.write("img.png", self.AWS_SAMPLE)
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


class HookInstallTest(unittest.TestCase):
    """install-hook / uninstall-hook"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        if preflight.git_out(self.tmp, ["--version"])[0] != 0:
            self.skipTest("本机没有 git")
        preflight.git_out(self.tmp, ["init", "-q"])
        self.hooks = os.path.join(self.tmp, ".git", "hooks")
        self.hook = os.path.join(self.hooks, "pre-commit")
        self.backup = os.path.join(self.hooks, "pre-commit.lunyu.bak")

    def write_hook(self, content):
        os.makedirs(self.hooks, exist_ok=True)
        with open(self.hook, "w", encoding="utf-8") as f:
            f.write(content)

    def read(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_install_creates_hook(self):
        ok, lines = preflight.install_hook(self.tmp)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(self.hook))
        body = self.read(self.hook)
        self.assertTrue(body.startswith("#!/bin/sh"))
        self.assertIn(preflight.HOOK_MARKER, body)
        self.assertIn("preflight.py", body)
        self.assertTrue(any("已安装" in s for s in lines))
        self.assertTrue(any("uninstall-hook" in s for s in lines))

    def test_install_backs_up_existing_hook(self):
        self.write_hook("#!/bin/sh\necho old-hook\n")
        ok, lines = preflight.install_hook(self.tmp)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(self.backup))
        self.assertIn("old-hook", self.read(self.backup))
        self.assertIn(preflight.HOOK_MARKER, self.read(self.hook))
        self.assertTrue(any("备份" in s for s in lines))

    def test_uninstall_restores_backup(self):
        self.write_hook("#!/bin/sh\necho old-hook\n")
        preflight.install_hook(self.tmp)
        ok, lines = preflight.uninstall_hook(self.tmp)
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(self.backup))
        self.assertEqual(self.read(self.hook), "#!/bin/sh\necho old-hook\n")
        self.assertTrue(any("恢复" in s for s in lines))

    def test_uninstall_without_hook(self):
        ok, lines = preflight.uninstall_hook(self.tmp)
        self.assertTrue(ok)
        self.assertFalse(os.path.exists(self.hook))
        self.assertTrue(any("无需删除" in s for s in lines))

    def test_uninstall_keeps_foreign_hook(self):
        self.write_hook("#!/bin/sh\necho someone-else\n")
        ok, lines = preflight.uninstall_hook(self.tmp)
        self.assertTrue(ok)
        self.assertIn("someone-else", self.read(self.hook))

    def test_install_uses_core_hooks_path(self):
        custom = os.path.join(self.tmp, "githooks")
        os.makedirs(custom, exist_ok=True)
        preflight.git_out(self.tmp, ["config", "core.hooksPath", "githooks"])
        ok, _ = preflight.install_hook(self.tmp)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(os.path.join(custom, "pre-commit")))
        self.assertFalse(os.path.exists(self.hook))

    def test_install_fails_outside_repo(self):
        plain = tempfile.mkdtemp()
        ok, lines = preflight.install_hook(plain)
        self.assertFalse(ok)
        self.assertTrue(any("git" in s for s in lines))


class DepsScanTest(unittest.TestCase):
    """依赖扫描 + SBOM"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def write(self, rel, content):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def sbom_path(self):
        return os.path.join(self.tmp, ".lunyu", "sbom.json")

    def test_no_manifest_skips_gracefully(self):
        rep = preflight.Report()
        self.assertIsNone(preflight.scan_deps(self.tmp, rep))
        self.assertEqual(rep.warnings, [])
        self.assertEqual(rep.blockers, [])
        self.assertTrue(any("跳过依赖扫描" in i for i in rep.infos))
        self.assertFalse(os.path.exists(self.sbom_path()))

    def test_unpinned_version_warns(self):
        self.write("requirements.txt", "requests\n-r other.txt\n# 注释\nflask==2.0.1\n")
        rep = preflight.Report()
        preflight.scan_deps(self.tmp, rep)
        self.assertTrue(any("未固定版本" in w for w in rep.warnings))
        self.assertTrue(any(w.startswith("依赖未固定版本 1 项") for w in rep.warnings))
        self.assertEqual(rep.blockers, [])

    def test_pinned_and_lockfile_no_warn(self):
        self.write("requirements.txt", "flask==2.0.1\n")
        self.write("requirements.lock", "flask==2.0.1\n")
        rep = preflight.Report()
        preflight.scan_deps(self.tmp, rep)
        self.assertEqual(rep.warnings, [])

    def test_missing_lockfile_warns(self):
        self.write("package.json", json.dumps({"dependencies": {"lodash": "4.17.21"}}))
        rep = preflight.Report()
        preflight.scan_deps(self.tmp, rep)
        self.assertTrue(any("lockfile" in w for w in rep.warnings))
        self.assertTrue(any("package-lock.json" in w for w in rep.warnings))

    def test_npm_caret_warns(self):
        self.write("package.json", json.dumps({"dependencies": {"lodash": "^4.17.21"}}))
        self.write("package-lock.json", "{}")
        rep = preflight.Report()
        preflight.scan_deps(self.tmp, rep)
        self.assertTrue(any("未固定版本" in w and "lodash" in w for w in rep.warnings))

    def test_risky_package_warns(self):
        self.write("requirements.txt", "requsts==1.0.0\n")
        self.write("requirements.lock", "requsts==1.0.0\n")
        rep = preflight.Report()
        preflight.scan_deps(self.tmp, rep)
        self.assertTrue(any("高风险依赖" in w and "requsts" in w for w in rep.warnings))

    def test_sbom_written(self):
        self.write("requirements.txt", "flask==2.0.1\nrequests\n")
        rep = preflight.Report()
        sbom = preflight.scan_deps(self.tmp, rep)
        self.assertTrue(os.path.exists(self.sbom_path()))
        with open(self.sbom_path(), "r", encoding="utf-8") as f:
            disk = json.load(f)
        self.assertEqual(disk["summary"]["total"], 2)
        self.assertEqual(sbom["dependencies"][0]["source"], "requirements.txt")
        self.assertEqual(sbom["dependencies"][0]["name"], "flask")
        self.assertEqual(sbom["dependencies"][0]["version"], "==2.0.1")
        self.assertEqual(sbom["dependencies"][1]["issues"][0], "未固定版本(空)")

    def test_pom_missing_version_warns(self):
        self.write("pom.xml", "<project><dependencies><dependency>"
                              "<artifactId>guava</artifactId>"
                              "</dependency></dependencies></project>")
        rep = preflight.Report()
        preflight.scan_deps(self.tmp, rep)
        self.assertTrue(any("未固定版本" in w and "guava" in w for w in rep.warnings))
        self.assertEqual(rep.blockers, [])

    def test_gradle_parsed(self):
        self.write("build.gradle", "dependencies {\n  implementation 'com.google.guava:guava:31.0'\n}\n")
        rep = preflight.Report()
        sbom = preflight.scan_deps(self.tmp, rep)
        self.assertEqual(len(sbom["dependencies"]), 1)
        self.assertEqual(sbom["dependencies"][0]["name"], "guava")
        self.assertEqual(sbom["dependencies"][0]["version"], "31.0")

    def test_broken_manifest_blocks(self):
        self.write("package.json", "{not-json")
        rep = preflight.Report()
        preflight.scan_deps(self.tmp, rep)
        self.assertTrue(any("解析失败" in b for b in rep.blockers))

    def test_is_unpinned_rules(self):
        self.assertFalse(preflight.is_unpinned("==2.0.1", "pip"))
        self.assertTrue(preflight.is_unpinned(">=2.0", "pip"))
        self.assertTrue(preflight.is_unpinned("", "pip"))
        self.assertTrue(preflight.is_unpinned("*", "npm"))
        self.assertTrue(preflight.is_unpinned("~1.2", "npm"))
        self.assertFalse(preflight.is_unpinned("1.2.3", "npm"))
        self.assertTrue(preflight.is_unpinned("LATEST", "maven"))
        self.assertFalse(preflight.is_unpinned("1.0.0", "maven"))


if __name__ == "__main__":
    unittest.main()