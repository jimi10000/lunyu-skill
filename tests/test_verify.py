#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify.py 单元测试

验证「证据先于声明」这条铁律真的被强制执行:
- 测试命令探测：项目自带入口优先于生态默认（探测错会把全绿跑成失败）
- 无测试能力的项目跳过，不误报「未验证」
- 有能力却不跑 = 未验证，strict 下阻断
- 证据落盘 .lunyu/verify.json
- record 手工登记：没证据要警告
- require：没有记录就阻断交付
- show 无记录返回 1
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import verify


class Args(object):
    def __init__(self, **kw):
        self.root = None
        self.json = False
        self.strict = False
        self.skip_tests = False
        self.skip_build = False
        self.timeout = 60
        self.item = None
        self.result = None
        self.evidence = None
        self.by = None
        self.__dict__.update(kw)


class DetectTest(unittest.TestCase):
    """探测是最容易翻车的地方——顺序错了全绿项目会被跑成失败"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def w(self, name, content=""):
        p = os.path.join(self.tmp, name)
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_project_entry_wins_over_pytest(self):
        """有 tests/run_tests.py 就不能去用 pytest"""
        self.w("tests/run_tests.py", "print('ok')\n")
        self.w("tests/test_a.py", "def test_a(): pass\n")
        cmd, src = verify.detect_test_command(self.tmp)
        self.assertIsNotNone(cmd)
        self.assertIn("run_tests.py", " ".join(cmd))
        self.assertNotIn("pytest", " ".join(cmd))

    def test_makefile_test_target(self):
        self.w("Makefile", "test:\n\tpytest -q\n")
        cmd, src = verify.detect_test_command(self.tmp)
        self.assertEqual(cmd, ["make", "test"])

    def test_node_project(self):
        self.w("package.json", json.dumps({"scripts": {"test": "jest"}}))
        cmd, _ = verify.detect_test_command(self.tmp)
        self.assertEqual(cmd, ["npm", "test"])

    def test_node_without_test_script_ignored(self):
        """没有 test 脚本的 package.json 不该被当成有测试"""
        self.w("package.json", json.dumps({"scripts": {"build": "tsc"}}))
        cmd, _ = verify.detect_test_command(self.tmp)
        self.assertIsNone(cmd)

    def test_go_project(self):
        self.w("go.mod", "module x\n")
        cmd, _ = verify.detect_test_command(self.tmp)
        self.assertEqual(cmd, ["go", "test", "./..."])

    def test_empty_project_no_test_command(self):
        """空项目不该报「未验证」——没能力就不检查"""
        self.assertIsNone(verify.detect_test_command(self.tmp)[0])

    def test_has_py_tests(self):
        self.w("tests/test_a.py", "def test_a(): pass\n")
        self.assertTrue(verify.has_py_tests(self.tmp))

    def test_no_py_tests(self):
        self.w("src/main.py", "print(1)\n")
        self.assertFalse(verify.has_py_tests(self.tmp))


class CheckItemTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".git"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tests_skipped_when_no_capability(self):
        item = verify.check_tests(self.tmp)
        self.assertEqual(item["status"], "skip", "没测试能力却报了状态: %s" % item["status"])

    def test_tests_unverified_when_not_run(self):
        """有能力却不跑 = 未验证，不能放过"""
        with open(os.path.join(self.tmp, "tests.py"), "w") as f:
            pass
        os.makedirs(os.path.join(self.tmp, "tests"), exist_ok=True)
        with open(os.path.join(self.tmp, "tests", "test_a.py"), "w") as f:
            f.write("def test_a(): pass\n")
        item = verify.check_tests(self.tmp, run=False)
        self.assertEqual(item["status"], "unverified")

    def test_handover_missing_is_skip(self):
        self.assertEqual(verify.check_handover(self.tmp)["status"], "skip")

    def test_handover_with_todo_warns(self):
        with open(os.path.join(self.tmp, "HANDOVER.md"), "w", encoding="utf-8") as f:
            f.write("# 交接\n待补\n待补\n待补\n")
        self.assertEqual(verify.check_handover(self.tmp)["status"], "warn")

    def test_known_gaps_not_declared_warns(self):
        with open(os.path.join(self.tmp, "HANDOVER.md"), "w", encoding="utf-8") as f:
            f.write("# 交接\n下一步：无\n")
        self.assertEqual(verify.check_known_gaps(self.tmp)["status"], "warn")

    def test_known_gaps_declared_passes(self):
        with open(os.path.join(self.tmp, "HANDOVER.md"), "w", encoding="utf-8") as f:
            f.write("# 交接\n## 已知未闭环\n- 无\n")
        self.assertEqual(verify.check_known_gaps(self.tmp)["status"], "pass")


class RecordRequireTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".git"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_record_writes_evidence(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = verify.cmd_record(Args(root=self.tmp, item="真机实测",
                                        result="pass", evidence="截图 a.png"))
        self.assertEqual(rc, 0)
        data = json.load(open(os.path.join(self.tmp, ".lunyu", "verify.json"),
                              encoding="utf-8"))
        self.assertEqual(data["recorded"]["真机实测"]["result"], "pass")
        self.assertEqual(data["recorded"]["真机实测"]["evidence"], "截图 a.png")

    def test_record_without_evidence_warns(self):
        buf, err = io.StringIO(), io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            rc = verify.cmd_record(Args(root=self.tmp, item="UI验收", result="pass"))
        self.assertEqual(rc, 0)
        self.assertIn("证据", err.getvalue(), "没填证据却没警告")

    def test_show_without_record_fails(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = verify.cmd_show(Args(root=self.tmp))
        self.assertEqual(rc, 1)

    def test_require_blocks_when_no_record(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = verify.cmd_require(Args(root=self.tmp, item="真机实测"))
        self.assertEqual(rc, 1, "没有验证记录却不阻断，等于没门禁")
        self.assertIn("阻断", buf.getvalue())

    def test_require_passes_with_manual_record(self):
        verify.cmd_record(Args(root=self.tmp, item="真机实测", result="pass",
                               evidence="截图 a.png"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = verify.cmd_require(Args(root=self.tmp, item="真机实测"))
        self.assertEqual(rc, 0)

    def test_require_blocks_failed_record(self):
        verify.cmd_record(Args(root=self.tmp, item="真机实测", result="fail",
                               evidence="崩了"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = verify.cmd_require(Args(root=self.tmp, item="真机实测"))
        self.assertEqual(rc, 1)


class SummarizeTest(unittest.TestCase):
    def test_counts(self):
        items = [{"status": "pass"}, {"status": "fail"}, {"status": "unverified"},
                 {"status": "skip"}, {"status": "warn"}]
        c = verify.summarize(items)
        self.assertEqual((c["pass"], c["fail"], c["unverified"], c["skip"], c["warn"]),
                         (1, 1, 1, 1, 1))


if __name__ == "__main__":
    unittest.main()
