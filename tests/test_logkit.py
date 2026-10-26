#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""logkit.py 单元测试

不再「write 出去再读回同一个常量」的同义反复，而是真的驱动 main() 生成：
- 文件确实落盘且内容含预期分类常量（并能被 Python 真实加载使用）
- 目录结构正确（python / ts / both 三种布局各不相同）
- --dest 指向不存在的深层目录能自动创建，默认 dest 落在 CWD 下
- 重复生成幂等
- 非法参数、dest 是普通文件时必须失败（返回非 0 且不产出文件）
"""
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import logkit  # noqa: E402

PY_FILES = ("__init__.py", "core.py", "example.py", "README.md")
TS_FILES = ("core.ts", "example.ts", "README.md")


def run_main(argv):
    """跑一次 logkit.main()，返回 (返回码, stdout, stderr)。"""
    out, err = io.StringIO(), io.StringIO()
    with patch.object(sys, "argv", ["logkit.py"] + argv), \
            redirect_stdout(out), redirect_stderr(err):
        rc = logkit.main()
    return rc, out.getvalue(), err.getvalue()


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_generated(path, name):
    """把生成出来的 .py 当模块真实加载一遍：能加载才是真的生成成功。"""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GeneratePythonTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dest = os.path.join(self.tmp, "src", "logkit")

    def test_generates_expected_files(self):
        rc, out, _ = run_main(["init", "--lang", "python", "--dest", self.dest])
        self.assertEqual(rc, 0)
        self.assertIn("已生成 4 个文件", out)
        for name in PY_FILES:
            self.assertTrue(os.path.isfile(os.path.join(self.dest, name)), name)
        # 目录结构: 单语言时文件直落 dest, 不额外套一层 logkit/
        self.assertEqual(sorted(os.listdir(self.dest)), sorted(PY_FILES))

    def test_generated_core_is_loadable_and_usable(self):
        run_main(["init", "--lang", "python", "--dest", self.dest])
        core = load_generated(os.path.join(self.dest, "core.py"), "logkit_gen_core")
        # 分类常量是真的在生成物里, 不是从 logkit.TS_CORE 读回来的
        self.assertEqual(core.CATEGORIES["payment"], "支付交易")
        self.assertIn("security", core.CATEGORIES)
        self.assertTrue(callable(core.get_logger))
        self.assertTrue(callable(core.setup))
        log = core.get_logger("payment")
        self.assertTrue(callable(log.info))
        self.assertEqual(core.current_trace_id(), "-")

    def test_generated_init_reexports_api(self):
        run_main(["init", "--lang", "python", "--dest", self.dest])
        text = read_text(os.path.join(self.dest, "__init__.py"))
        for sym in ("get_logger", "setup", "trace", "timed", "CATEGORIES"):
            self.assertIn(sym, text)

    def test_deep_dest_is_auto_created(self):
        dest = os.path.join(self.tmp, "a", "b", "c", "logkit")
        self.assertFalse(os.path.exists(os.path.dirname(dest)))
        rc, _, _ = run_main(["init", "--lang", "python", "--dest", dest])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(os.path.join(dest, "core.py")))

    def test_default_dest_is_cwd_logkit(self):
        cwd = os.getcwd()
        os.chdir(self.tmp)
        try:
            rc, _, _ = run_main(["init"])
            self.assertEqual(rc, 0)
        finally:
            os.chdir(cwd)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "logkit", "core.py")))

    def test_regenerate_is_idempotent(self):
        rc1, _, _ = run_main(["init", "--lang", "python", "--dest", self.dest])
        with open(os.path.join(self.dest, "core.py"), "rb") as f:
            before = f.read()
        rc2, _, _ = run_main(["init", "--lang", "python", "--dest", self.dest])
        with open(os.path.join(self.dest, "core.py"), "rb") as f:
            after = f.read()
        self.assertEqual((rc1, rc2), (0, 0))
        self.assertEqual(before, after)
        self.assertTrue(before)


class GenerateTsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dest = os.path.join(self.tmp, "src", "logkit")

    def test_generates_expected_files(self):
        rc, out, _ = run_main(["init", "--lang", "ts", "--dest", self.dest])
        self.assertEqual(rc, 0)
        self.assertIn("已生成 3 个文件", out)
        for name in TS_FILES:
            self.assertTrue(os.path.isfile(os.path.join(self.dest, name)), name)

    def test_generated_core_has_expected_content(self):
        run_main(["init", "--lang", "ts", "--dest", self.dest])
        core = read_text(os.path.join(self.dest, "core.ts"))
        self.assertIn("export const CATEGORIES", core)
        self.assertIn("payment: '支付交易'", core)
        self.assertIn("export function getLogger", core)
        self.assertIn("export async function timed", core)
        self.assertIn("traceId", core)
        # ts 版不该混进 python 产物
        self.assertFalse(os.path.exists(os.path.join(self.dest, "core.py")))


class GenerateBothTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dest = os.path.join(self.tmp, "src")

    def test_both_uses_lang_subdirs(self):
        rc, out, _ = run_main(["init", "--lang", "both", "--dest", self.dest])
        self.assertEqual(rc, 0)
        self.assertIn("已生成 7 个文件", out)
        py_dir = os.path.join(self.dest, "logkit")
        ts_dir = os.path.join(self.dest, "ts")
        self.assertEqual(sorted(os.listdir(py_dir)), sorted(PY_FILES))
        self.assertEqual(sorted(os.listdir(ts_dir)), sorted(TS_FILES))
        # 两种语言分开落盘, 不互相覆盖 README
        self.assertNotEqual(
            read_text(os.path.join(py_dir, "README.md")),
            read_text(os.path.join(ts_dir, "README.md")),
        )


class FailureTest(unittest.TestCase):
    """失败路径必须真的失败: 返回非 0 且不产出文件。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dest = os.path.join(self.tmp, "logkit")

    def test_invalid_lang_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            run_main(["init", "--lang", "ruby", "--dest", self.dest])
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertFalse(os.path.exists(self.dest), "非法参数不应产出任何文件")

    def test_dest_on_existing_file_fails(self):
        os.makedirs(self.tmp, exist_ok=True)
        with open(self.dest, "w", encoding="utf-8") as f:
            f.write("i am a file, not a dir")
        rc, out, err = run_main(["init", "--lang", "python", "--dest", self.dest])
        self.assertEqual(rc, 1)
        self.assertIn("生成失败", err)
        self.assertNotIn("已生成", out)
        self.assertFalse(os.path.exists(os.path.join(self.dest, "core.py")))

    def test_write_creates_nested_dirs(self):
        p = os.path.join(self.tmp, "a", "b", "c.txt")
        self.assertEqual(logkit.write(p, "hi"), p)
        self.assertEqual(read_text(p), "hi")


if __name__ == "__main__":
    unittest.main()
