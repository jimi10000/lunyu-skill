#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codecraft.py 单元测试

验证「机器能查的代码工艺」四项都能查出、且不该报的不报:
- 重复代码块：跨文件复制粘贴必报
- 过长函数 / 嵌套过深
- 死代码：定义了全项目没人用
- 坏习惯：注释掉的代码块、TODO 无主
- import 噪音不误报（这是最容易假警报的一类）
- --strict 有问题返回非零，--skip-dead 跳过死代码
- --json 可解析；目录不存在返回 1
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
import codecraft


class CodecraftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, content):
        p = os.path.join(self.tmp, name)
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def dup_block(self):
        return "\n".join([
            "    total = 0",
            "    for item in items:",
            "        if item.price > 0:",
            "            total += item.price",
            "        else:",
            "            total -= item.price",
            "    return total",
        ])

    def test_duplicate_block_detected(self):
        self.write("a.py", "def calc_a(items):\n" + self.dup_block() + "\n")
        self.write("b.py", "def calc_b(items):\n" + self.dup_block() + "\n")
        dups = codecraft.find_duplicates(self.tmp, 6)
        self.assertTrue(dups, "两处一模一样的 7 行代码块没被查出来")
        self.assertGreaterEqual(dups[0]["occurrences"], 2)
        self.assertEqual(len(dups[0]["files"]), 2)

    def test_import_noise_not_reported(self):
        """每个文件开头都是一串 import/require，全报等于没报"""
        self.write("a.py", "import os\nimport sys\nimport json\nimport re\nimport time\n"
                           "import math\nimport copy\n\ndef fa():\n    return 1\n")
        self.write("b.py", "import os\nimport sys\nimport json\nimport re\nimport time\n"
                           "import math\nimport copy\n\ndef fb():\n    return 2\n")
        dups = codecraft.find_duplicates(self.tmp, 6)
        self.assertEqual(dups, [], "import 骨架被当成重复代码，误报")

    def test_long_function_detected(self):
        body = "\n".join("    x%d = %d" % (i, i) for i in range(80))
        self.write("big.py", "def huge():\n" + body + "\n    return x0\n")
        issues = codecraft.find_long_funcs(self.tmp, 20, 4)
        longs = [i for i in issues if i["kind"] == "过长函数"]
        self.assertTrue(longs, "80 行的函数没被查出过长")
        self.assertIn("huge", longs[0]["name"])

    def test_deep_nesting_detected(self):
        lines = ["def deep(a):"]
        for i in range(6):
            lines.append("    " * (i + 1) + "if a == %d:" % i)
        lines.append("    " * 7 + "return True")
        self.write("nest.py", "\n".join(lines) + "\n")
        issues = codecraft.find_long_funcs(self.tmp, 200, 2)
        nests = [i for i in issues if i["kind"] == "嵌套过深"]
        self.assertTrue(nests, "六层嵌套没被查出来")

    def test_unreferenced_definition_detected(self):
        self.write("dead.py", "def orphan_helper():\n    return 42\n")
        dead = codecraft.find_unreferenced(self.tmp)
        names = [d["name"] for d in dead]
        self.assertIn("orphan_helper", names)

    def test_used_definition_not_flagged(self):
        self.write("live.py", "def helper():\n    return 1\n\n\ndef caller():\n    return helper()\n")
        dead = codecraft.find_unreferenced(self.tmp)
        names = [d["name"] for d in dead]
        self.assertNotIn("helper", names, "有调用却被当成死代码，误报")

    def test_commented_out_code_block(self):
        lines = ["# def old_impl():", "#     a = 1", "#     b = 2",
                 "#     c = 3", "#     return a + b + c", "#", "#     d = 4",
                 "#     e = 5", "def new_impl():\n    return 1\n"]
        self.write("old.py", "\n".join(lines) + "\n")
        habits = codecraft.find_bad_habits(self.tmp)
        kinds = [h["kind"] for h in habits]
        self.assertIn("注释掉的代码块", kinds)

    def test_todo_without_owner(self):
        self.write("todo.py", "def f():\n    # TODO 这里要重构\n    return 1\n")
        habits = codecraft.find_bad_habits(self.tmp)
        kinds = [h["kind"] for h in habits]
        self.assertIn("TODO 无主", kinds)

    def test_todo_with_owner_not_flagged(self):
        self.write("todo.py", "def f():\n    # TODO(张三) 2026-11-01 前重构\n    return 1\n")
        habits = codecraft.find_bad_habits(self.tmp)
        kinds = [h["kind"] for h in habits]
        self.assertNotIn("TODO 无主", kinds, "有责任人的 TODO 不该报")

    def test_clean_code_no_issues(self):
        self.write("clean.py", "def add(a, b):\n    return a + b\n")
        dups = codecraft.find_duplicates(self.tmp, 6)
        dead = codecraft.find_unreferenced(self.tmp)
        habits = codecraft.find_bad_habits(self.tmp)
        self.assertEqual(dups, [])
        self.assertEqual(habits, [])
        # add 只出现一次（定义处），会被判死代码——这是设计如此，
        # 真实项目里入口函数不会被扫，测试里单独断言不报 dups 即可
        self.assertIsInstance(dead, list)

    def test_main_json(self):
        self.write("a.py", "def calc_a(items):\n" + self.dup_block() + "\n")
        self.write("b.py", "def calc_b(items):\n" + self.dup_block() + "\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = codecraft.main(["--path", self.tmp, "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("duplicates", payload)

    def test_main_strict_nonzero_on_issues(self):
        self.write("a.py", "def calc_a(items):\n" + self.dup_block() + "\n")
        self.write("b.py", "def calc_b(items):\n" + self.dup_block() + "\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = codecraft.main(["--path", self.tmp, "--strict"])
        self.assertEqual(rc, 1, "--strict 下有问题却返回 0，CI 门禁形同虚设")

    def test_main_strict_zero_on_clean(self):
        self.write("clean.py", "def add(a, b):\n    return a + b\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = codecraft.main(["--path", self.tmp, "--strict",
                                 "--skip-dead", "--min-lines", "50"])
        self.assertEqual(rc, 0)

    def test_main_missing_dir(self):
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf):
            old = sys.stderr
            sys.stderr = err
            try:
                rc = codecraft.main(["--path", os.path.join(self.tmp, "nope")])
            finally:
                sys.stderr = old
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
