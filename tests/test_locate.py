#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""locate.py 单元测试

验证「接手陌生代码库先找到东西在哪」:
- --keyword：文件名命中优先于内容命中（说明这文件就是干这事的）
- 定义处权重高于普通引用
- 测试文件降权（找实现时先看实现）
- --entry 找入口点
- --route 按路径过滤路由
- --config 配置定义优先于读取处
- 目录不存在返回 1
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
import locate


class Args(object):
    def __init__(self, **kw):
        self.root = None
        self.limit = 20
        self.max_lines = 5
        self.json = False
        self.keyword = None
        self.entry = False
        self.route = None
        self.config = None
        self.__dict__.update(kw)


class LocateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def w(self, name, content):
        p = os.path.join(self.tmp, name)
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_keyword_finds_by_filename(self):
        self.w("src/pay.py", "def charge(x):\n    return x\n")
        self.w("src/order.py", "from pay import charge\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = locate.cmd_keyword(Args(root=self.tmp, keyword="pay"))
        self.assertEqual(rc, 0)
        self.assertIn("pay.py", buf.getvalue())

    def test_filename_hit_ranks_above_content_hit(self):
        """文件名命中说明这文件就是干这事的，必须排在前面"""
        self.w("src/pay.py", "def x(): pass\n")
        self.w("src/other.py", "# pay pay pay pay\n# pay\n# pay\n# pay\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            locate.cmd_keyword(Args(root=self.tmp, keyword="pay"))
        out = buf.getvalue()
        self.assertLess(out.index("pay.py"), out.index("other.py"))

    def test_test_files_demoted(self):
        """找实现时，测试文件不该排在实现前面"""
        self.w("src/pay.py", "def charge(): pass\n")
        self.w("tests/test_pay.py", "def test_charge(): pass\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            locate.cmd_keyword(Args(root=self.tmp, keyword="charge"))
        out = buf.getvalue()
        self.assertLess(out.index("src/pay.py"), out.index("tests/test_pay.py"))

    def test_definition_marked(self):
        self.w("src/pay.py", "def charge(x):\n    return x\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            locate.cmd_keyword(Args(root=self.tmp, keyword="charge"))
        self.assertIn("定义处", buf.getvalue())

    def test_keyword_not_found(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = locate.cmd_keyword(Args(root=self.tmp, keyword="不存在的东西"))
        self.assertEqual(rc, 0)
        self.assertIn("没找到", buf.getvalue())

    def test_keyword_json(self):
        self.w("src/pay.py", "def charge(): pass\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = locate.cmd_keyword(Args(root=self.tmp, keyword="charge", json=True))
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertTrue(payload["hits"])

    def test_entry_detection(self):
        self.w("main.py", "def main():\n    print(1)\n\nif __name__ == '__main__':\n    main()\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = locate.cmd_entry(Args(root=self.tmp))
        self.assertEqual(rc, 0)
        self.assertIn("main.py", buf.getvalue())

    def test_route_filter(self):
        self.w("api.py", "router.get('/api/pay', handler)\nrouter.get('/api/order', h2)\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = locate.cmd_route(Args(root=self.tmp, route="/api/pay"))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn("/api/pay", out)
        self.assertNotIn("/api/order", out)

    def test_route_not_found(self):
        self.w("api.py", "router.get('/api/pay', handler)\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = locate.cmd_route(Args(root=self.tmp, route="/nope"))
        self.assertEqual(rc, 0)
        self.assertIn("没找到", buf.getvalue())

    def test_config_definition_before_reader(self):
        self.w("app.yaml", "db.host: localhost\n")
        self.w("src/db.py", "host = os.getenv('db.host')\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = locate.cmd_config(Args(root=self.tmp, config="db.host"))
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertLess(out.index("[配置]"), out.index("[读取处]"))

    def test_missing_dir_returns_1(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = locate.cmd_keyword(Args(root=os.path.join(self.tmp, "nope"),
                                         keyword="x"))
        self.assertEqual(rc, 1)

    def test_skip_dirs_respected(self):
        """node_modules 这类目录不该被扫"""
        self.w("node_modules/lib/pay.js", "function pay(){}\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            locate.cmd_keyword(Args(root=self.tmp, keyword="pay"))
        self.assertNotIn("node_modules", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
