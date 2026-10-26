#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scheduler.py 单元测试

验证:
- 脚本路径定位
- Windows 命令构建（绕开 bash）
- run() 处理超时/不存在
- is_windows 判断
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import scheduler


class PathTest(unittest.TestCase):
    def test_find_skill_dir(self):
        d = scheduler.find_skill_dir()
        self.assertTrue(d.endswith("lunyu"))
        self.assertTrue(os.path.isdir(os.path.join(d, "scripts")))

    def test_get_report_py(self):
        p = scheduler.get_report_py()
        self.assertTrue(os.path.isfile(p))

    def test_get_daily_script(self):
        p = scheduler.get_daily_script()
        self.assertTrue(os.path.isfile(p))


class WindowsCmdTest(unittest.TestCase):
    def test_build_windows_cmd(self):
        with patch.object(scheduler, "get_report_py", return_value="C:/lunyu/scripts/report.py"), \
             patch.object(scheduler.sys, "executable", "C:/Python/python.exe"):
            cmd = scheduler.build_windows_cmd("C:/My Project", "老板")
        self.assertIn("report.py", cmd)
        self.assertIn('"C:/Python/python.exe"', cmd)
        self.assertIn("--project", cmd)
        self.assertIn("老板", cmd)
        self.assertIn("--body", cmd)


class RunTest(unittest.TestCase):
    def test_run_timeout(self):
        with patch.object(scheduler.subprocess, "run",
                          side_effect=FileNotFoundError("no git")):
            rc, out = scheduler.run(["whatever"])
        self.assertEqual(rc, 1)
        self.assertIn("no git", out)

    def test_run_ok(self):
        with patch.object(scheduler.subprocess, "run") as m:
            m.return_value.returncode = 0
            m.return_value.stdout = "ok"
            m.return_value.stderr = ""
            rc, out = scheduler.run(["echo", "x"])
        self.assertEqual(rc, 0)
        self.assertEqual(out, "ok")


class PlatformTest(unittest.TestCase):
    def test_is_windows(self):
        with patch.object(scheduler.platform, "system", return_value="Windows"):
            self.assertTrue(scheduler.is_windows())
        with patch.object(scheduler.platform, "system", return_value="Linux"):
            self.assertFalse(scheduler.is_windows())


class InstallTest(unittest.TestCase):
    def test_install_missing_report(self):
        with patch.object(scheduler, "get_report_py", return_value="/nonexistent/report.py"):
            class A:
                time = "18:00"
                project = "C:/proj"
                author = "me"
            rc = scheduler.cmd_install(A())
        self.assertEqual(rc, 1)

    def test_install_windows_ok(self):
        import tempfile
        tmp = tempfile.mkdtemp()
        fake_report = os.path.join(tmp, "report.py")
        with open(fake_report, "w", encoding="utf-8") as f:
            f.write("# fake report")
        with patch.object(scheduler, "is_windows", return_value=True), \
             patch.object(scheduler, "get_report_py", return_value=fake_report), \
             patch.object(scheduler, "run", return_value=(0, "success")), \
             patch.object(scheduler.sys, "executable", "C:/Python/python.exe"):
            class A:
                time = "18:00"
                project = "C:/proj"
                author = "me"
            rc = scheduler.cmd_install(A())
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()