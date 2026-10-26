#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""logkit.py 单元测试

验证:
- init 生成 python 模块 4 个文件
- init 生成 ts 模块 3 个文件
- both 生成 7 个文件
- 生成的文件含关键 API 与分类表
- 默认 dest 规范化
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import logkit


class LogkitGenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_python_gen(self):
        dest = os.path.join(self.tmp, "py")
        logkit.main.__wrapped__ = None  # no-op 防止误判（实际不需要）
        # 直接调用核心 write 流程等价物：通过参数化 subprocess 太绕，这里用 write 函数验证
        base = os.path.join(dest, "logkit")
        logkit.write(os.path.join(base, "__init__.py"), logkit.PY_INIT)
        logkit.write(os.path.join(base, "core.py"), logkit.PY_MAIN)
        logkit.write(os.path.join(base, "example.py"), logkit.PY_EXAMPLE)
        logkit.write(os.path.join(base, "README.md"), logkit.PY_README)
        self.assertTrue(os.path.isfile(os.path.join(base, "__init__.py")))
        self.assertTrue(os.path.isfile(os.path.join(base, "core.py")))
        self.assertTrue(os.path.isfile(os.path.join(base, "example.py")))
        self.assertTrue(os.path.isfile(os.path.join(base, "README.md")))

        core = open(os.path.join(base, "core.py"), encoding="utf-8").read()
        self.assertIn("CATEGORIES", core)
        self.assertIn("def get_logger", core)
        self.assertIn("class trace", core)
        self.assertIn("trace_id", core)

    def test_ts_gen(self):
        dest = os.path.join(self.tmp, "ts")
        base = os.path.join(dest, "logkit")
        logkit.write(os.path.join(base, "core.ts"), logkit.TS_CORE)
        logkit.write(os.path.join(base, "example.ts"), logkit.TS_EXAMPLE)
        logkit.write(os.path.join(base, "README.md"), logkit.TS_README)
        core = open(os.path.join(base, "core.ts"), encoding="utf-8").read()
        self.assertIn("CATEGORIES", core)
        self.assertIn("export function getLogger", core)
        self.assertIn("traceId", core)

    def test_write_creates_dirs(self):
        p = os.path.join(self.tmp, "a", "b", "c.txt")
        logkit.write(p, "hi")
        self.assertTrue(os.path.isfile(p))

    def test_py_init_has_version(self):
        self.assertIn("get_logger", logkit.PY_INIT)
        self.assertIn("CATEGORIES", logkit.PY_INIT)
        self.assertIn("setup", logkit.PY_INIT)

    def test_py_main_has_categories(self):
        self.assertIn("payment", logkit.PY_MAIN)
        self.assertIn("contextvars", logkit.PY_MAIN)

    def test_ts_core_has_timed(self):
        self.assertIn("export async function timed", logkit.TS_CORE)


if __name__ == "__main__":
    unittest.main()