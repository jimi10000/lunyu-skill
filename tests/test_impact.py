#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""impact.py 单元测试

用临时仓库模拟「改一个公共模块，看谁在用它」，验证:
- 代码引用能被找出来，并给出行号
- 测试覆盖单独分桶（有没有测一目了然）
- 配置/路由里的字符串引用能扫到（改类名时最容易漏这个）
- 跨仓库引用进 cross_repo
- 目标文件不存在返回 1
- --file / --symbol 都没给时参数校验失败
- --md / --json / --out 三种输出都可用
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import impact


class ImpactTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".git"), exist_ok=True)
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.src, exist_ok=True)
        self.down = tempfile.mkdtemp()

        # 公共模块
        self.pay = os.path.join(self.src, "pay.py")
        with open(self.pay, "w", encoding="utf-8") as f:
            f.write("def charge(amount):\n    return amount\n")
        # 调用方
        with open(os.path.join(self.src, "order.py"), "w", encoding="utf-8") as f:
            f.write("from pay import charge\n\n\ndef submit():\n    return charge(100)\n")
        # 测试
        tdir = os.path.join(self.tmp, "tests")
        os.makedirs(tdir, exist_ok=True)
        with open(os.path.join(tdir, "test_pay.py"), "w", encoding="utf-8") as f:
            f.write("from pay import charge\n\n\ndef test_charge():\n    assert charge(1)\n")
        # 配置里的字符串引用
        with open(os.path.join(self.tmp, "app.json"), "w", encoding="utf-8") as f:
            f.write('{"handler": "charge"}\n')
        # 下游仓库
        with open(os.path.join(self.down, "client.py"), "w", encoding="utf-8") as f:
            f.write("import charge\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.down, ignore_errors=True)

    def test_symbols_from_file(self):
        syms = impact.symbols_from_file(self.pay)
        self.assertIn("charge", syms)

    def test_finds_code_reference_with_line(self):
        buckets, cross, scanned = impact.analyze(["charge"], self.tmp)
        files = [e["file"] for e in buckets["代码引用"]]
        self.assertTrue(any("order.py" in f for f in files))
        entry = [e for e in buckets["代码引用"] if "order.py" in e["file"]][0]
        self.assertTrue(entry["lines"])
        self.assertIsInstance(entry["lines"][0]["no"], int)

    def test_test_coverage_bucket(self):
        buckets, _, _ = impact.analyze(["charge"], self.tmp)
        covered = [e["file"] for e in buckets["测试覆盖"]]
        self.assertTrue(any("test_pay.py" in f for f in covered),
                        "有测试却没归到测试覆盖桶，等于没发现覆盖率")

    def test_config_reference_bucket(self):
        """改类名时配置里的字符串最容易漏——必须能扫到"""
        buckets, _, _ = impact.analyze(["charge"], self.tmp)
        cfg = [e["file"] for e in buckets["配置引用"]]
        self.assertTrue(any(f.endswith(".json") for f in cfg))

    def test_cross_repo_reference(self):
        buckets, cross, _ = impact.analyze(["charge"], self.tmp, [self.down])
        self.assertTrue(cross, "下游仓库引用没进 cross_repo")
        self.assertNotEqual(cross[0]["repo"], "main")

    def test_definition_bucket(self):
        buckets, _, _ = impact.analyze(["charge"], self.tmp)
        defs = [e["file"] for e in buckets["定义处"]]
        self.assertTrue(any("pay.py" in f for f in defs))

    def test_main_file_not_found(self):
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf):
            old = sys.stderr
            sys.stderr = err
            try:
                rc = impact.main(["--file", "nope.py", "--root", self.tmp])
            finally:
                sys.stderr = old
        self.assertEqual(rc, 1)

    def test_requires_target(self):
        """没给 --file 也没给 --symbol，argparse error 抛 SystemExit(2)"""
        with self.assertRaises(SystemExit) as ctx:
            impact.main(["--root", self.tmp])
        self.assertEqual(ctx.exception.code, 2)

    def test_md_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = impact.main(["--symbol", "charge", "--root", self.tmp, "--md"])
        self.assertEqual(rc, 0)
        self.assertIn("影响面分析", buf.getvalue())

    def test_json_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = impact.main(["--symbol", "charge", "--root", self.tmp, "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["symbols"], ["charge"])
        self.assertIn("buckets", payload)

    def test_out_writes_file(self):
        out = os.path.join(self.tmp, "影响面分析.md")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = impact.main(["--symbol", "charge", "--root", self.tmp,
                              "--md", "--out", out])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(out))
        self.assertIn("charge", open(out, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
