#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bug_ledger.py 单元测试

用临时目录模拟 .lunyu/bugs.json 台账，验证:
- add / list / show / update / stats / export
- 关闭缺陷记录 closed_at，重开清除 closed_at
- 门禁校验: 存在未关闭 P0/P1 时 stats 返回 1
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
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭"))
        data = bug_ledger.load(self.path)
        self.assertIn("closed_at", data["bugs"][0])

    def test_reopen_clears_closed_at(self):
        bug_ledger.cmd_add(self.make_args(title="x", priority="P3", status="新建"))
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭"))
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
        bug_ledger.cmd_add(self.make_args(title="b", priority="P2", status="关闭"))
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
        bug_ledger.cmd_update(self.make_args(id="BUG-0001", status="关闭"))
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


if __name__ == "__main__":
    unittest.main()