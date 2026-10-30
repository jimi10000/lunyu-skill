#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""plan.py 单元测试

验证「每个任务必须有验收点」这条纪律被强制执行:
- 没写验收点不许建任务（这是本脚本存在的意义）
- 从 md 的 - [ ] 批量导入
- 状态流转 todo → doing → done
- --strict 下完成必须带证据
- gate：未完成的阻断；没验收点的也阻断
- clear 需要 --yes 确认
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
import plan


class Args(object):
    def __init__(self, **kw):
        self.root = None
        self.id = None
        self.title = None
        self.acceptance = None
        self.from_file = None
        self.evidence = None
        self.strict = False
        self.json = False
        self.yes = False
        self.__dict__.update(kw)


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".git"), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def plan_path(self):
        return os.path.join(self.tmp, ".lunyu", "plan.json")

    def add(self, title="任务", acceptance="跑测试全绿"):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = plan.cmd_new(Args(root=self.tmp, title=title, acceptance=acceptance))
        self.assertEqual(rc, 0, buf.getvalue())
        return 1

    def test_new_requires_acceptance(self):
        """没验收点不许建——这是 plan.py 存在的全部意义"""
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = plan.cmd_new(Args(root=self.tmp, title="改支付"))
        self.assertEqual(rc, 2)
        self.assertIn("验收点", err.getvalue())

    def test_new_requires_title(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = plan.cmd_new(Args(root=self.tmp, acceptance="全绿"))
        self.assertEqual(rc, 2)

    def test_new_writes_plan(self):
        self.add()
        data = json.load(open(self.plan_path(), encoding="utf-8"))
        self.assertEqual(len(data["tasks"]), 1)
        self.assertEqual(data["tasks"][0]["acceptance"], "跑测试全绿")
        self.assertEqual(data["tasks"][0]["status"], plan.STATUS_TODO)

    def test_import_from_md(self):
        p = os.path.join(self.tmp, "方案.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write("# 方案\n- [ ] 抽出校验函数\n- [ ] 补测试\n- [x] 已完成的\n")
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = plan.cmd_new(Args(root=self.tmp, from_file="方案.md"))
        self.assertEqual(rc, 0)
        data = json.load(open(self.plan_path(), encoding="utf-8"))
        self.assertEqual(len(data["tasks"]), 3)
        self.assertEqual(data["tasks"][2]["status"], plan.STATUS_DONE)
        self.assertIn("验收点", err.getvalue(), "导入的任务缺验收点却没警告")

    def test_import_missing_file(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = plan.cmd_new(Args(root=self.tmp, from_file="不存在.md"))
        self.assertEqual(rc, 1)

    def test_status_flow(self):
        self.add()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(plan.cmd_start(Args(root=self.tmp, id=1)), 0)
        data = json.load(open(self.plan_path(), encoding="utf-8"))
        self.assertEqual(data["tasks"][0]["status"], plan.STATUS_DOING)

        with redirect_stdout(io.StringIO()):
            self.assertEqual(plan.cmd_done(Args(root=self.tmp, id=1,
                                                evidence="384 全绿")), 0)
        data = json.load(open(self.plan_path(), encoding="utf-8"))
        self.assertEqual(data["tasks"][0]["status"], plan.STATUS_DONE)
        self.assertEqual(data["tasks"][0]["evidence"], "384 全绿")

    def test_done_strict_requires_evidence(self):
        self.add()
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = plan.cmd_done(Args(root=self.tmp, id=1, strict=True))
        self.assertEqual(rc, 2, "strict 下没证据却放行")
        self.assertIn("证据", err.getvalue())

    def test_reset(self):
        self.add()
        with redirect_stdout(io.StringIO()):
            plan.cmd_done(Args(root=self.tmp, id=1, evidence="ok"))
            rc = plan.cmd_reset(Args(root=self.tmp, id=1))
        self.assertEqual(rc, 0)
        data = json.load(open(self.plan_path(), encoding="utf-8"))
        self.assertEqual(data["tasks"][0]["status"], plan.STATUS_TODO)

    def test_set_acceptance(self):
        # new 不允许空验收点，这里手工塞一个没验收点的任务再补
        self.add(acceptance="旧的")
        data = json.load(open(self.plan_path(), encoding="utf-8"))
        data["tasks"][0]["acceptance"] = ""
        json.dump(data, open(self.plan_path(), "w", encoding="utf-8"))
        with redirect_stdout(io.StringIO()):
            rc = plan.cmd_set_acceptance(Args(root=self.tmp, id=1,
                                              acceptance="接口返回 200"))
        self.assertEqual(rc, 0)
        data = json.load(open(self.plan_path(), encoding="utf-8"))
        self.assertEqual(data["tasks"][0]["acceptance"], "接口返回 200")

    def test_gate_blocks_undone(self):
        self.add()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = plan.cmd_gate(Args(root=self.tmp))
        self.assertEqual(rc, 1)
        self.assertIn("阻断", buf.getvalue())

    def test_gate_passes_all_done(self):
        self.add()
        with redirect_stdout(io.StringIO()):
            plan.cmd_done(Args(root=self.tmp, id=1, evidence="ok"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = plan.cmd_gate(Args(root=self.tmp))
        self.assertEqual(rc, 0)

    def test_gate_blocks_missing_acceptance(self):
        self.add()
        data = json.load(open(self.plan_path(), encoding="utf-8"))
        data["tasks"][0]["acceptance"] = ""
        data["tasks"][0]["status"] = plan.STATUS_DONE
        json.dump(data, open(self.plan_path(), "w", encoding="utf-8"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = plan.cmd_gate(Args(root=self.tmp))
        self.assertEqual(rc, 1, "全做完但没验收点却放行")
        self.assertIn("验收点", buf.getvalue())

    def test_clear_needs_confirm(self):
        self.add()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = plan.cmd_clear(Args(root=self.tmp))
        self.assertEqual(rc, 1)
        self.assertIn("--yes", buf.getvalue())

    def test_clear_with_yes(self):
        self.add()
        with redirect_stdout(io.StringIO()):
            rc = plan.cmd_clear(Args(root=self.tmp, yes=True))
        self.assertEqual(rc, 0)
        data = json.load(open(self.plan_path(), encoding="utf-8"))
        self.assertEqual(data["tasks"], [])

    def test_list_shows_progress(self):
        self.add(title="改支付")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = plan.cmd_list(Args(root=self.tmp))
        self.assertEqual(rc, 0)
        self.assertIn("进度: 0/1", buf.getvalue())
        self.assertIn("改支付", buf.getvalue())

    def test_empty_plan_gate_passes(self):
        """没拆任务不该阻断——不是每个改动都要拆"""
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = plan.cmd_gate(Args(root=self.tmp))
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
