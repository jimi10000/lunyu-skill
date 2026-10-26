#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bug_ledger.py 单元测试

用临时目录模拟 .lunyu/bugs.json 台账，验证:
- add / list / show / update / stats / export
- 关闭缺陷记录 closed_at，重开清除 closed_at
- 关闭门禁: 缺 root_cause / regression 时阻断(退出码 1)，--force 可豁免
- 门禁校验: 存在未关闭 P0/P1 时 stats 返回 1
- 容错: 坏 JSON 台账不崩
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import bug_ledger


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".git"), exist_ok=True)  # 让 find_root 找到
        self.path = os.path.join(self.tmp, ".lunyu", "bugs.json")

    def make_args(self, **kw):
        class A:
            pass
        a = A()
        a.root = self.tmp
        # 给所有可能访问到的属性设默认值
        defaults = {
            "title": "默认标题",
            "priority": "P2",
            "status": "新建",
            "repro": "",
            "expected": "",
            "related_pr": "",
            "related_version": "",
            "root_cause": "",
            "regression": "",
            "force": False,
            "note": None,
            "out": None,
            "id": None,
        }
        for k, v in defaults.items():
            setattr(a, k, v)
        for k, v in kw.items():
            setattr(a, k, v)
        return a

    def test_add_and_show(self):
        args = self.make_args(title="按钮不响应", priority="P1", status="新建",
                              repro="点击无反应", expected="点击应有反馈")
        bug_ledger.cmd_add(args)
        data = bug_ledger.load(self.path)
        self.assertEqual(len(data["bugs"]), 1)
        self.assertEqual(data["next_id"], 2)
        bug = data["bugs"][0]
        self.assertEqual(bug["id"], "BUG-0001")
        self.assertEqual(bug["priority"], "P1")
        self.assertEqual(bug["status"], "新建")
        self.assertIn("created_at", bug)
        self.assertIn("history", bug)
        # show
        buf = io.StringIO()
        with redirect_stdout(buf):
            bug_ledger.cmd_show(self.make_args(id="bug-0001"))
        self.assertIn("BUG-0001", buf.getvalue())

    def test_show_missing_exit1(self):
        with self.assertRaises(SystemExit) as ctx:
            bug_ledger.cmd_show(self.make_args(id="BUG-9999"))
        self.assertEqual(ctx.exception.code, 1)

    def test_update_priority_and_status(self):
        bug_ledger.cmd_add(self.make_args(title="x", priority="P2", status="新建"))
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", priority="P0", status="修复中"))
        data = bug_ledger.load(self.path)
        bug = data["bugs"][0]
        self.assertEqual(bug["priority"], "P0")
        self.assertEqual(bug["status"], "修复中")
        self.assertNotIn("closed_at", bug)

    def test_close_records_closed_at(self):
        bug_ledger.cmd_add(self.make_args(title="x", priority="P3", status="新建"))
        # 新语义: 关闭必须带根因 + 回归用例
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭",
                                             root_cause="编码疏漏",
                                             regression="tests/test_x.py::test_y"))
        data = bug_ledger.load(self.path)
        self.assertIn("closed_at", data["bugs"][0])
        self.assertEqual(data["bugs"][0]["regression"], "tests/test_x.py::test_y")

    def test_reopen_clears_closed_at(self):
        bug_ledger.cmd_add(self.make_args(title="x", priority="P3", status="新建"))
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭",
                                             root_cause="测试漏测",
                                             regression="pytest tests/test_x.py"))
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="重开"))
        data = bug_ledger.load(self.path)
        self.assertNotIn("closed_at", data["bugs"][0])

    def test_invalid_status_exit1(self):
        bug_ledger.cmd_add(self.make_args(title="x", priority="P3", status="新建"))
        with self.assertRaises(SystemExit) as ctx:
            bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="不存在"))
        self.assertEqual(ctx.exception.code, 1)

    def test_list_filters(self):
        bug_ledger.cmd_add(self.make_args(title="a", priority="P0", status="新建"))
        # 以「关闭」状态登记必须带防复发证据（关闭门禁）
        bug_ledger.cmd_add(self.make_args(title="b", priority="P2", status="关闭",
                                          root_cause="编码疏漏",
                                          regression="tests/test_b.py"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            bug_ledger.cmd_list(self.make_args(priority=None, status=None, open_only=False))
        self.assertIn("BUG-0001", buf.getvalue())
        self.assertIn("BUG-0002", buf.getvalue())
        buf = io.StringIO()
        with redirect_stdout(buf):
            bug_ledger.cmd_list(self.make_args(priority="P2", status=None, open_only=False))
        self.assertNotIn("BUG-0001", buf.getvalue())
        self.assertIn("BUG-0002", buf.getvalue())

    def test_stats_gate_blocker(self):
        bug_ledger.cmd_add(self.make_args(title="严重崩溃", priority="P0", status="新建"))
        rc = bug_ledger.cmd_stats(self.make_args())
        self.assertEqual(rc, 1)  # 门禁不通过

    def test_stats_gate_pass_when_closed(self):
        bug_ledger.cmd_add(self.make_args(title="严重崩溃", priority="P0", status="新建"))
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭",
                                             root_cause="设计问题",
                                             regression="tests/test_crash.py"))
        rc = bug_ledger.cmd_stats(self.make_args())
        self.assertEqual(rc, 0)  # 门禁通过

    def test_export(self):
        bug_ledger.cmd_add(self.make_args(title="x", priority="P1", status="新建"))
        out = os.path.join(self.tmp, "bugs.md")
        bug_ledger.cmd_export(self.make_args(out=out))
        self.assertTrue(os.path.exists(out))
        with open(out, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("BUG-0001", content)
        self.assertIn("| 单号 |", content)


class CloseGateTest(unittest.TestCase):
    """关闭门禁：不迁怒，不贰过 —— 没留防复发证据不许关闭。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".git"), exist_ok=True)
        self.path = os.path.join(self.tmp, ".lunyu", "bugs.json")

    def make_args(self, **kw):
        class A:
            pass
        a = A()
        a.root = self.tmp
        defaults = {
            "title": "默认标题", "priority": "P2", "status": "新建",
            "repro": "", "expected": "", "related_pr": "", "related_version": "",
            "root_cause": "", "regression": "", "force": False,
            "note": None, "out": None, "id": None,
        }
        for k, v in defaults.items():
            setattr(a, k, v)
        for k, v in kw.items():
            setattr(a, k, v)
        return a

    def test_close_blocked_without_root_cause(self):
        bug_ledger.cmd_add(self.make_args(title="x", priority="P2", status="新建"))
        with self.assertRaises(SystemExit) as ctx:
            bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭",
                                                 regression="tests/test_x.py"))
        self.assertEqual(ctx.exception.code, 1)
        data = bug_ledger.load(self.path)
        self.assertNotEqual(data["bugs"][0]["status"], "关闭")  # 没写进去
        self.assertNotIn("closed_at", data["bugs"][0])

    def test_close_blocked_without_regression(self):
        bug_ledger.cmd_add(self.make_args(title="x", priority="P2", status="新建"))
        with self.assertRaises(SystemExit) as ctx:
            bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭",
                                                 root_cause="编码疏漏"))
        self.assertEqual(ctx.exception.code, 1)
        self.assertNotIn("closed_at", bug_ledger.load(self.path)["bugs"][0])

    def test_close_blocked_when_root_cause_is_undetermined(self):
        """root_cause 仍为「未定」等同没填，不算闭环。"""
        bug_ledger.cmd_add(self.make_args(title="x", priority="P2", status="新建"))
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", root_cause="未定"))
        with self.assertRaises(SystemExit) as ctx:
            bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭",
                                                 regression="tests/test_x.py"))
        self.assertEqual(ctx.exception.code, 1)

    def test_block_message_is_actionable(self):
        bug_ledger.cmd_add(self.make_args(title="x", priority="P2", status="新建"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭"))
        msg = buf.getvalue()
        self.assertIn("关闭必须填 root_cause 与 regression", msg)
        self.assertIn("--force", msg)

    def test_close_with_evidence_passes(self):
        bug_ledger.cmd_add(self.make_args(title="x", priority="P2", status="新建"))
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭",
                                             root_cause="需求问题",
                                             regression="pytest tests/test_x.py"))
        bug = bug_ledger.load(self.path)["bugs"][0]
        self.assertEqual(bug["status"], "关闭")
        self.assertEqual(bug["root_cause"], "需求问题")
        self.assertIn("closed_at", bug)

    def test_regression_recorded_before_close(self):
        """回归用例可以先登记，之后关闭时复用（不必一次给全）。"""
        bug_ledger.cmd_add(self.make_args(title="x", priority="P2", status="新建"))
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", regression="tests/test_x.py"))
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", root_cause="测试漏测"))
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭"))
        self.assertEqual(bug_ledger.load(self.path)["bugs"][0]["status"], "关闭")

    def test_force_close_bypasses_gate(self):
        """确属无法复现时用 --force 放行。"""
        bug_ledger.cmd_add(self.make_args(title="偶发闪退", priority="P2", status="新建"))
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭", force=True))
        bug = bug_ledger.load(self.path)["bugs"][0]
        self.assertEqual(bug["status"], "关闭")
        self.assertIn("closed_at", bug)

    def test_add_with_status_closed_blocked(self):
        with self.assertRaises(SystemExit) as ctx:
            bug_ledger.cmd_add(self.make_args(title="x", status="关闭"))
        self.assertEqual(ctx.exception.code, 1)
        self.assertFalse(os.path.exists(self.path))  # 未落盘

    def test_add_with_status_closed_and_evidence(self):
        bug_ledger.cmd_add(self.make_args(title="x", status="关闭",
                                          root_cause="编码疏漏",
                                          regression="tests/test_x.py"))
        bug = bug_ledger.load(self.path)["bugs"][0]
        self.assertEqual(bug["status"], "关闭")
        self.assertIn("closed_at", bug)

    def test_add_records_regression_field(self):
        bug_ledger.cmd_add(self.make_args(title="x", regression="tests/test_x.py"))
        self.assertEqual(bug_ledger.load(self.path)["bugs"][0]["regression"],
                         "tests/test_x.py")

    def test_non_closing_update_unaffected(self):
        """非关闭流转不受门禁影响。"""
        bug_ledger.cmd_add(self.make_args(title="x", priority="P2", status="新建"))
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="修复中"))
        self.assertEqual(bug_ledger.load(self.path)["bugs"][0]["status"], "修复中")

    def test_missing_evidence_helper(self):
        self.assertEqual(bug_ledger.missing_evidence({"root_cause": "未定"}, ""),
                         ["root_cause(根因)", "regression(回归用例)"])
        self.assertEqual(bug_ledger.missing_evidence({"root_cause": "编码疏漏"},
                                                     "tests/test_x.py"), [])


class ToleranceTest(unittest.TestCase):
    """容错：文件不存在 / 坏 JSON 都不能崩。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".git"), exist_ok=True)
        self.path = os.path.join(self.tmp, ".lunyu", "bugs.json")

    def test_load_missing_file(self):
        self.assertEqual(bug_ledger.load(os.path.join(self.tmp, "nope.json")),
                         {"next_id": 1, "bugs": []})

    def test_load_bad_json(self):
        os.makedirs(os.path.join(self.tmp, ".lunyu"), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ 这不是 json")
        self.assertEqual(bug_ledger.load(self.path), {"next_id": 1, "bugs": []})

    def test_update_on_bad_json_does_not_crash(self):
        os.makedirs(os.path.join(self.tmp, ".lunyu"), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("[]")  # 结构异常
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(io.StringIO()):
                bug_ledger.cmd_update(type("A", (), {
                    "root": self.tmp, "id": "BUG-0001", "status": None,
                    "priority": None, "root_cause": None, "regression": None,
                    "related_version": None, "related_pr": None, "note": None,
                    "force": False})())
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()