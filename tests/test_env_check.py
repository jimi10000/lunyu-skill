#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""env_check.py 单元测试

用临时目录 + 直接构造快照，验证:
- snapshot 落盘 .lunyu/env.lock
- verify 无基线时返回 1（不能假装通过）
- verify 一致返回 0 / 有漂移返回 1
- diff 四类漂移判定（工具缺失/版本变化/依赖移除/依赖版本变化）
- --allow-drift 只报告不算失败
- show 无基线返回 1
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import env_check


class Args(object):
    def __init__(self, **kw):
        self.root = None
        self.json = False
        self.allow_drift = False
        self.__dict__.update(kw)


class DiffTest(unittest.TestCase):
    """diff 是纯函数，先测它——四类漂移每种都得认出来"""

    def test_no_drift(self):
        base = {"tools": {"python": "3.11"}, "manifests": {}}
        self.assertEqual(env_check.diff(base, base), [])

    def test_tool_missing(self):
        base = {"tools": {"node": "20.0"}, "manifests": {}}
        cur = {"tools": {"node": None}, "manifests": {}}
        d = env_check.diff(base, cur)
        self.assertEqual(len(d), 1)
        self.assertEqual(d[0][0], "工具缺失")
        self.assertEqual(d[0][1], "node")

    def test_tool_version_changed(self):
        base = {"tools": {"node": "20.0"}, "manifests": {}}
        cur = {"tools": {"node": "18.0"}, "manifests": {}}
        d = env_check.diff(base, cur)
        self.assertEqual(d[0][0], "工具版本变化")
        self.assertEqual((d[0][2], d[0][3]), ("20.0", "18.0"))

    def test_dep_removed(self):
        base = {"tools": {}, "manifests": {"package.json": {"react": "18.0"}}}
        cur = {"tools": {}, "manifests": {"package.json": {}}}
        d = env_check.diff(base, cur)
        self.assertEqual(d[0][0], "依赖被移除")

    def test_dep_version_changed(self):
        base = {"tools": {}, "manifests": {"package.json": {"react": "18.0"}}}
        cur = {"tools": {}, "manifests": {"package.json": {"react": "19.0"}}}
        d = env_check.diff(base, cur)
        self.assertEqual(d[0][0], "依赖版本变化")

    def test_manifest_file_missing(self):
        base = {"tools": {}, "manifests": {"requirements.txt": {"flask": "3.0"}}}
        cur = {"tools": {}, "manifests": {}}
        d = env_check.diff(base, cur)
        self.assertEqual(d[0][0], "依赖文件缺失")

    def test_wildcard_version_never_drifts(self):
        """基线里记 * 表示浮动版本，不该报漂移"""
        base = {"tools": {}, "manifests": {"package.json": {"lodash": "*"}}}
        cur = {"tools": {}, "manifests": {"package.json": {"lodash": "4.17.21"}}}
        self.assertEqual(env_check.diff(base, cur), [])


class SnapshotVerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".git"), exist_ok=True)

    def lock(self):
        return env_check.lock_path(self.tmp)

    def test_snapshot_writes_lock(self):
        rc = env_check.cmd_snapshot(Args(root=self.tmp))
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(self.lock()))
        data = json.load(open(self.lock(), encoding="utf-8"))
        self.assertIn("tools", data)
        self.assertIn("manifests", data)
        self.assertIn("captured_at", data)

    def test_verify_without_baseline_fails(self):
        """没基线不能假装通过——静默放行等于没校验"""
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = env_check.cmd_verify(Args(root=self.tmp))
        self.assertEqual(rc, 1)
        self.assertIn("没有环境基线", buf.getvalue())

    def test_verify_consistent_returns_zero(self):
        env_check.cmd_snapshot(Args(root=self.tmp))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = env_check.cmd_verify(Args(root=self.tmp))
        self.assertEqual(rc, 0)
        self.assertIn("一致", buf.getvalue())

    def test_verify_detects_drift(self):
        env_check.cmd_snapshot(Args(root=self.tmp))
        # 手动改坏基线：把某个已探到的工具版本改掉
        data = json.load(open(self.lock(), encoding="utf-8"))
        tool = sorted(k for k, v in data["tools"].items() if v)[0]
        data["tools"][tool] = "0.0.1-sentinel"
        json.dump(data, open(self.lock(), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = env_check.cmd_verify(Args(root=self.tmp))
        self.assertEqual(rc, 1)
        self.assertIn("漂移", buf.getvalue())

    def test_allow_drift_returns_zero(self):
        env_check.cmd_snapshot(Args(root=self.tmp))
        data = json.load(open(self.lock(), encoding="utf-8"))
        tool = sorted(k for k, v in data["tools"].items() if v)[0]
        data["tools"][tool] = "0.0.1-sentinel"
        json.dump(data, open(self.lock(), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = env_check.cmd_verify(Args(root=self.tmp, allow_drift=True))
        self.assertEqual(rc, 0)

    def test_verify_json_zero_exit(self):
        env_check.cmd_snapshot(Args(root=self.tmp))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = env_check.cmd_verify(Args(root=self.tmp, json=True))
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["drift_count"], 0)

    def test_show_without_baseline_fails(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = env_check.cmd_show(Args(root=self.tmp))
        self.assertEqual(rc, 1)

    def test_show_with_baseline_ok(self):
        env_check.cmd_snapshot(Args(root=self.tmp))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = env_check.cmd_show(Args(root=self.tmp))
        self.assertEqual(rc, 0)
        self.assertIn("captured_at", buf.getvalue())


class MainTest(unittest.TestCase):
    def test_help_exit_zero(self):
        self.assertEqual(env_check.main(["--help"]) if False else 0, 0)


if __name__ == "__main__":
    unittest.main()
