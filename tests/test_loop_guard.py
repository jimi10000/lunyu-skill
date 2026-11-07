#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""loop_guard.py 单元测试：检测、归因、报告、预算、损坏文件处理。"""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import loop_guard as g  # noqa: E402


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="lg_")
        self.root = os.path.join(self.tmp, "proj")
        os.makedirs(os.path.join(self.root, ".git"))
        self.trace = g.store_path(self.root)[1]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def log(self, action="动作", status="fail", error="", signature=""):
        return g.main(["log", "--root", self.root, "--action", action,
                       "--status", status, "--error", error,
                       "--signature", signature])

    def write_steps(self, steps, budget=40):
        g.write_state(self.trace, {"budget": budget, "steps": steps})

    def step(self, action="a", status="fail", error="", sig="a"):
        return {"ts": "2026-01-01T00:00:00", "action": action, "status": status,
                "error": error, "cmd_sig": sig,
                "err_sig": g.err_signature(error)}

    # ── 错误签名归一化 ──
    def test_err_signature_normalizes_volatile_parts(self):
        a = g.err_signature("ModuleNotFoundError: foo at line 12 (0.31s) 2026-11-07T10:00:00Z")
        b = g.err_signature("ModuleNotFoundError: foo at line 98 (1.72s) 2026-11-07T11:20:00Z")
        self.assertEqual(a, b, "同一错误换时间戳/行号/耗时仍应聚成同一个签名")
        self.assertNotEqual(a, g.err_signature("PermissionError: denied"))
        self.assertEqual("", g.err_signature(""))

    def test_err_signature_strips_temp_paths(self):
        a = g.err_signature("FileNotFoundError: /tmp/tmpabc123/x.py not found")
        b = g.err_signature("FileNotFoundError: /tmp/tmpdef456/y.py not found")
        self.assertEqual(a, b)

    # ── 五类检测 ──
    def test_repeat_cmd(self):
        f = g.detect([self.step(sig="pytest")] * 3)
        self.assertIn("repeat_cmd", [x["type"] for x in f])

    def test_repeat_cmd_different_actions_not_flagged(self):
        steps = [self.step(sig="a"), self.step(sig="b"), self.step(sig="c")]
        self.assertNotIn("repeat_cmd", [x["type"] for x in g.detect(steps)])

    def test_repeat_error_across_commands(self):
        steps = [self.step(sig="a", error="OSError: disk full"),
                 self.step(sig="b", error="OSError: disk full"),
                 self.step(sig="c", error="OSError: disk full")]
        f = g.detect(steps)
        self.assertIn("repeat_error", [x["type"] for x in f])

    def test_fail_streak(self):
        steps = [self.step(status="fail")] * 3 + [self.step(status="ok")]
        self.assertIn("fail_streak", [x["type"] for x in g.detect(steps)])

    def test_ok_breaks_fail_streak(self):
        steps = [self.step(status="fail"), self.step(status="ok"),
                 self.step(status="fail"), self.step(status="ok"),
                 self.step(status="fail"), self.step(status="ok")]
        self.assertNotIn("fail_streak", [x["type"] for x in g.detect(steps)])

    def test_no_progress(self):
        steps = [self.step(status="fail", sig="x%d" % i) for i in range(6)]
        self.assertIn("no_progress", [x["type"] for x in g.detect(steps)])

    def test_budget(self):
        steps = [self.step(status="ok", sig="x%d" % i) for i in range(10)]
        self.assertIn("budget", [x["type"] for x in g.detect(steps, budget=10)])
        self.assertNotIn("budget", [x["type"] for x in g.detect(steps, budget=40)])

    def test_clean_run_has_no_finding(self):
        steps = [self.step(status="ok", sig="x%d" % i) for i in range(5)]
        self.assertEqual([], g.detect(steps))

    # ── 归因 ──
    def test_cause_env_drift(self):
        steps = [self.step(error="ModuleNotFoundError: No module named foo")] * 3
        c = g.rank_causes(steps, [])
        self.assertEqual("ENV_DRIFT", c[0]["code"])

    def test_cause_wrong_path(self):
        steps = [self.step(error="FileNotFoundError: No such file or directory")] * 3
        c = g.rank_causes(steps, [])
        self.assertEqual("WRONG_PATH", c[0]["code"])

    def test_unknown_cause_is_honest(self):
        c = g.rank_causes([self.step(error="xyz")], [])
        self.assertEqual("UNKNOWN", c[0]["code"])
        self.assertIn("不要编", c[0]["action"])

    def test_every_cause_has_verification(self):
        for c in g.CAUSES:
            self.assertTrue(c["verify"], "%s 缺验证方法" % c["code"])
            self.assertTrue(c["action"], "%s 缺建议动作" % c["code"])

    # ── 命令层 ──
    def test_check_exit_codes(self):
        self.assertEqual(0, g.main(["check", "--root", self.root]))
        for _ in range(3):
            self.log(error="OSError: disk full")
        self.assertEqual(1, g.main(["check", "--root", self.root]),
                         "检测到失控必须返回 1 供门禁使用")

    def test_check_json(self):
        for _ in range(3):
            self.log(error="boom")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = g.main(["check", "--root", self.root, "--json"])
        d = json.loads(buf.getvalue())
        self.assertEqual(1, rc)
        self.assertTrue(d["stuck"])
        self.assertTrue(d["findings"])

    def test_report_contains_all_sections(self):
        for _ in range(3):
            self.log(error="ModuleNotFoundError: foo")
        out = os.path.join(self.tmp, "报告.md")
        self.assertEqual(0, g.main(["report", "--root", self.root, "--out", out]))
        text = open(out, encoding="utf-8").read()
        for key in ["现象", "证据", "可能原因", "必须停下来", "建议下一步", "需要用户确认"]:
            self.assertIn(key, text, "报告缺「%s」段" % key)
        self.assertIn("env_check.py", text, "报告应给出可执行的验证命令")

    def test_reset_requires_yes(self):
        self.log()
        self.assertEqual(2, g.main(["reset", "--root", self.root]))
        self.assertTrue(os.path.isfile(self.trace))
        self.assertEqual(0, g.main(["reset", "--root", self.root, "--yes"]))
        self.assertEqual([], g.read_state(self.trace)["steps"])

    def test_budget_command(self):
        self.assertEqual(0, g.main(["budget", "--root", self.root, "--max", "7"]))
        self.assertEqual(7, g.read_state(self.trace)["budget"])
        self.assertEqual(2, g.main(["budget", "--root", self.root, "--max", "0"]))

    def test_trace_capped(self):
        for i in range(g.MAX_TRACE + 12):
            self.log(action="a%d" % i, status="ok")
        self.assertEqual(g.MAX_TRACE, len(g.read_state(self.trace)["steps"]))

    def test_corrupt_trace_exits_3(self):
        os.makedirs(os.path.dirname(self.trace), exist_ok=True)
        with open(self.trace, "w", encoding="utf-8") as f:
            f.write("{ broken json")
        with self.assertRaises(SystemExit) as cm:
            g.read_state(self.trace)
        self.assertEqual(3, cm.exception.code, "轨迹损坏不能静默吞掉")

    def test_no_subcommand_prints_help(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = g.main([])
        self.assertEqual(0, rc)
        self.assertIn("usage", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
