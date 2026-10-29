#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""handover.py 单元测试

验证交接产物这个「跨会话唯一能留下的东西」:
- 生成的 HANDOVER.md 五段齐全（状态/已完成/下一步/未决决策/已知坑）
- 能采到 git 分支、最近提交、工作区改动
- 未关闭缺陷与经验库被带进「已知坑」
- --step / --note 能写进去
- --read 无文档返回 1，有文档返回 0
- --json 输出可被解析
- 非 git 仓库不炸（降级为「非 git 仓库」）
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import handover


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


class HandoverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_git_repo(self):
        run(["git", "init", "-q"], self.tmp)
        run(["git", "config", "user.email", "test@test.com"], self.tmp)
        run(["git", "config", "user.name", "test"], self.tmp)
        with open(os.path.join(self.tmp, "a.txt"), "w", encoding="utf-8") as f:
            f.write("hello\n")
        run(["git", "add", "."], self.tmp)
        run(["git", "commit", "-q", "-m", "init: 第一次提交"], self.tmp)

    def test_generate_creates_file(self):
        self.make_git_repo()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = handover.main(["--root", self.tmp])
        self.assertEqual(rc, 0)
        p = os.path.join(self.tmp, "HANDOVER.md")
        self.assertTrue(os.path.isfile(p))
        return open(p, encoding="utf-8").read()

    def test_five_sections_present(self):
        text = self.test_generate_creates_file()
        for sec in ("当前状态", "已完成", "下一步", "未决决策", "已知坑"):
            self.assertIn(sec, text, "交接文档缺「%s」段" % sec)

    def test_collects_git_info(self):
        self.make_git_repo()
        info = handover.collect(self.tmp)
        self.assertNotEqual(info["branch"], "（非 git 仓库）")
        self.assertTrue(info["commits"] or info["head"])

    def test_collects_dirty_worktree(self):
        self.make_git_repo()
        with open(os.path.join(self.tmp, "b.txt"), "w", encoding="utf-8") as f:
            f.write("dirty\n")
        info = handover.collect(self.tmp)
        self.assertGreater(info["dirty_count"], 0)

    def test_step_and_note_recorded(self):
        self.make_git_repo()
        info = handover.collect(self.tmp, step="5", note="跑 impact.py 确认调用方")
        self.assertEqual(info["step"], "5")
        self.assertEqual(info["note"], "跑 impact.py 确认调用方")
        text = handover.render(info)
        self.assertIn("跑 impact.py 确认调用方", text)

    def test_open_bugs_into_known_pits(self):
        """未关闭缺陷是接手人最容易踩的坑，必须出现在交接文档里"""
        self.make_git_repo()
        d = os.path.join(self.tmp, ".lunyu")
        os.makedirs(d, exist_ok=True)
        json.dump({"bugs": [{"id": "B1", "title": "支付偶发超时", "status": "打开"}]},
                  open(os.path.join(d, "bugs.json"), "w", encoding="utf-8"))
        info = handover.collect(self.tmp)
        self.assertEqual(info["open_bug_count"], 1)
        self.assertIn("支付偶发超时", handover.render(info))

    def test_read_without_doc_fails(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = handover.main(["--root", self.tmp, "--read"])
        self.assertEqual(rc, 1)

    def test_read_with_doc_ok(self):
        self.make_git_repo()
        with redirect_stdout(io.StringIO()):
            handover.main(["--root", self.tmp])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = handover.main(["--root", self.tmp, "--read"])
        self.assertEqual(rc, 0)
        self.assertIn("HANDOVER", buf.getvalue())

    def test_json_output(self):
        self.make_git_repo()
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = handover.main(["--root", self.tmp, "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("branch", payload)
        self.assertIn("commits", payload)

    def test_non_git_repo_degrades_gracefully(self):
        """不是 git 仓库也要能出文档，不能炸"""
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = handover.main(["--root", self.tmp])
        self.assertEqual(rc, 0)
        info = handover.collect(self.tmp)
        self.assertEqual(info["branch"], "（非 git 仓库）")

    def test_custom_out_path(self):
        self.make_git_repo()
        out = os.path.join(tempfile.mkdtemp(), "nested", "HANDOVER.md")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = handover.main(["--root", self.tmp, "--out", out])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.isfile(out))


if __name__ == "__main__":
    unittest.main()
