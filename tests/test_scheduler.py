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
import tempfile
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


class CronWriteTest(unittest.TestCase):
    def test_install_cron_writes_via_stdin(self):
        """回归: 写 crontab 必须走 stdin, 不能经 shell echo(repr 的 \n 是字面量,
        会把整个 crontab 压成一行坏条目)。"""
        _tmp = tempfile.mkdtemp()
        _fake = os.path.join(_tmp, "report.py")
        open(_fake, "w", encoding="utf-8").write("# fake")
        with patch.object(scheduler, "get_report_py", return_value=_fake), \
             patch.object(scheduler, "is_windows", return_value=False), \
             patch.object(scheduler, "get_daily_script", return_value="/s/daily_report.sh"), \
             patch.object(scheduler, "run", return_value=(0, "")), \
             patch.object(scheduler, "run_input", return_value=(0, "")) as ri:
            class A:
                time = "18:00"
                project = "/tmp/my proj"  # 含空格, 必须被引号包裹
                author = "me"
            rc = scheduler.cmd_install(A())
        self.assertEqual(rc, 0)
        args, _ = ri.call_args
        self.assertEqual(args[0], ["crontab", "-"])
        payload = args[1]
        # 跨平台: abspath 在 Windows 会把 /tmp/x 变成盘符路径, 故只断言结构
        self.assertIn('cd "', payload)          # 必须 cd 到项目目录
        self.assertIn("my proj", payload)       # 路径含空格仍被引号包裹
        self.assertIn('bash "/s/daily_report.sh"', payload)
        self.assertTrue(payload.endswith("\n"))
        # 字面量反斜杠n 说明发生了 repr 转义, 不允许出现
        self.assertNotIn("\\n", payload)

    def test_uninstall_cron_writes_via_stdin(self):
        """卸载重写 crontab 也必须走 stdin, 且保留无关条目。"""
        crontab_out = "keep me 0 9 * * 1\nlunyu_daily_report junk\n"
        with patch.object(scheduler, "is_windows", return_value=False), \
             patch.object(scheduler, "run", return_value=(0, crontab_out)), \
             patch.object(scheduler, "run_input", return_value=(0, "")) as ri:
            rc = scheduler.cmd_uninstall(None)
        self.assertEqual(rc, 0)
        args, kwargs = ri.call_args
        self.assertEqual(args[0], ["crontab", "-"])
        self.assertIn("keep me", args[1])
        self.assertNotIn("lunyu_daily_report", args[1])

    def test_install_windows_sets_workdir(self):
        """回归: 计划任务默认 CWD 是 System32, /tr 必须先 cd 到项目目录。"""
        tmp = tempfile.mkdtemp()
        fake_report = os.path.join(tmp, "report.py")
        with open(fake_report, "w", encoding="utf-8") as f:
            f.write("# fake report")
        with patch.object(scheduler, "is_windows", return_value=True), \
             patch.object(scheduler, "get_report_py", return_value=fake_report), \
             patch.object(scheduler, "run", return_value=(0, "ok")) as m, \
             patch.object(scheduler.sys, "executable", "C:/Python/python.exe"):
            class A:
                time = "18:00"
                project = "C:/My Proj"
                author = "me"
            rc = scheduler.cmd_install(A())
        self.assertEqual(rc, 0)
        tr_value = m.call_args.args[0][5]
        self.assertIn('cd /d \\"C:\My Proj\\"', tr_value)
        # /tr 内层引号已转义
        self.assertIn('\\"', tr_value)


if __name__ == "__main__":
    unittest.main()