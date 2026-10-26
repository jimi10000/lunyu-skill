#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scheduler.py 单元测试

验证:
- 脚本路径定位
- Windows 命令构建（绕开 bash）
- run() 处理超时/不存在
- is_windows 判断
"""
import importlib.util
import io
import itertools
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import scheduler

REAL_SCHEDULER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "scheduler.py")
_mod_seq = itertools.count()


def load_scheduler_at(scripts_dir):
    """在临时目录里加载一份真实的 scheduler.py。

    __file__ 天然指向该目录，不需要 patch 被测模块本身；
    这样才能断言「路径解析」而不是断言「文件恰好存在」。
    """
    os.makedirs(scripts_dir, exist_ok=True)
    dst = os.path.join(scripts_dir, "scheduler.py")
    shutil.copyfile(REAL_SCHEDULER, dst)
    spec = importlib.util.spec_from_file_location("scheduler_under_test_%d" % next(_mod_seq), dst)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PathTest(unittest.TestCase):
    """路径解析必须算出「预期的那个具体路径」，而不是只要存在就算过。"""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.scripts = os.path.join(self.tmp, "scripts")
        self.mod = load_scheduler_at(self.scripts)

    def test_find_skill_dir_is_parent_of_scripts(self):
        self.assertEqual(self.mod.find_skill_dir(), self.tmp)
        self.assertEqual(os.path.dirname(self.scripts), self.tmp)
        # 不能把 scripts 自己当成技能根
        self.assertNotEqual(self.mod.find_skill_dir(), self.scripts)

    def test_get_report_py_path(self):
        p = self.mod.get_report_py()
        self.assertEqual(p, os.path.join(self.tmp, "scripts", "report.py"))
        self.assertEqual(os.path.basename(p), "report.py")
        # 父目录必须是技能根下的 scripts/
        self.assertEqual(os.path.dirname(os.path.dirname(p)), self.tmp)
        self.assertEqual(os.path.dirname(p), self.scripts)

    def test_get_daily_script_path(self):
        p = self.mod.get_daily_script()
        self.assertEqual(p, os.path.join(self.tmp, "scripts", "daily_report.sh"))
        self.assertEqual(os.path.dirname(p), self.scripts)
        self.assertNotEqual(p, self.mod.get_report_py())

    def test_paths_follow_relocated_module(self):
        """挪到另一个目录后路径必须跟着变（证明不是写死常量）。"""
        other = os.path.realpath(tempfile.mkdtemp())
        mod2 = load_scheduler_at(os.path.join(other, "scripts"))
        self.assertEqual(mod2.get_report_py(), os.path.join(other, "scripts", "report.py"))
        self.assertNotEqual(mod2.get_report_py(), self.mod.get_report_py())

    def test_missing_layout_reports_error(self):
        """目录结构不对（scripts/report.py 缺失）时必须报错退出，不能静默成功。"""
        self.assertFalse(os.path.isfile(self.mod.get_report_py()))

        class A:
            time = "18:00"
            project = self.tmp
            author = "me"

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = self.mod.cmd_install(A())
        self.assertEqual(rc, 1)
        self.assertIn("未找到 report.py", buf.getvalue())

    def test_installed_skill_layout_intact(self):
        """真实安装目录的布局没被改坏（冒烟，防止路径函数悄悄改错）。"""
        d = scheduler.find_skill_dir()
        self.assertEqual(os.path.basename(d), "lunyu")
        self.assertTrue(os.path.isfile(os.path.join(d, "SKILL.md")))
        self.assertTrue(os.path.isfile(os.path.join(d, "scripts", "report.py")))
        self.assertTrue(os.path.isfile(os.path.join(d, "scripts", "daily_report.sh")))


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