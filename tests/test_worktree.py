#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""worktree.py 单元测试

验证「多需求/多 AI 并行互不污染」:
- create 建出独立目录且分支正确
- 分支已存在时不许重复建
- 基准分支不存在时报错
- list 能列出工作区
- path 能拿到路径
- remove 有未提交改动时阻断（删了就没了）
- remove --force 能删
- 非 git 仓库返回 1

注：需要本机有 git。没有就整组跳过，不误报失败。
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import worktree


def has_git():
    try:
        r = subprocess.run(["git", "--version"], capture_output=True)
        return r.returncode == 0
    except OSError:
        return False


class Args(object):
    def __init__(self, **kw):
        self.root = None
        self.branch = None
        self.base = None
        self.dir = None
        self.force = False
        self.drop_branch = False
        self.__dict__.update(kw)


@unittest.skipUnless(has_git(), "本机没有 git")
class WorktreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "proj")
        os.makedirs(self.repo)
        self.git(["git", "init", "-q"])
        self.git(["git", "config", "user.email", "test@test.com"])
        self.git(["git", "config", "user.name", "test"])
        with open(os.path.join(self.repo, "a.txt"), "w", encoding="utf-8") as f:
            f.write("hello\n")
        self.git(["git", "add", "."])
        self.git(["git", "commit", "-q", "-m", "init"])
        self.git(["git", "branch", "-M", "main"])

    def tearDown(self):
        # 先清理 worktree 记录，否则临时目录删不掉
        subprocess.run(["git", "worktree", "prune"], cwd=self.repo,
                       capture_output=True)
        for root, dirs, _ in os.walk(self.tmp):
            for d in dirs:
                if d == ".git":
                    pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, cmd):
        return subprocess.run(cmd, cwd=self.repo, capture_output=True, text=True)

    def test_create_makes_isolated_dir(self):
        target = os.path.join(self.tmp, "wt-feature")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = worktree.cmd_create(Args(root=self.repo, branch="feat/x",
                                          base="main", dir=target))
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertTrue(os.path.isdir(target), "工作区目录没建出来")
        self.assertTrue(os.path.isfile(os.path.join(target, "a.txt")))

    def test_create_rejects_existing_branch(self):
        self.git(["git", "branch", "feat/exists"])
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = worktree.cmd_create(Args(root=self.repo, branch="feat/exists",
                                          base="main",
                                          dir=os.path.join(self.tmp, "w1")))
        self.assertEqual(rc, 1)
        self.assertIn("已存在", err.getvalue())

    def test_create_rejects_bad_base(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = worktree.cmd_create(Args(root=self.repo, branch="feat/y",
                                          base="不存在的分支",
                                          dir=os.path.join(self.tmp, "w2")))
        self.assertEqual(rc, 1)
        self.assertIn("基准分支", err.getvalue())

    def test_create_rejects_existing_dir(self):
        d = os.path.join(self.tmp, "已存在")
        os.makedirs(d, exist_ok=True)
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = worktree.cmd_create(Args(root=self.repo, branch="feat/z",
                                          base="main", dir=d))
        self.assertEqual(rc, 1)

    def test_list_and_path(self):
        target = os.path.join(self.tmp, "wt-list")
        with redirect_stdout(io.StringIO()):
            worktree.cmd_create(Args(root=self.repo, branch="feat/list",
                                     base="main", dir=target))
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = worktree.cmd_list(Args(root=self.repo))
        self.assertEqual(rc, 0)
        self.assertIn("feat/list", buf.getvalue())

        buf2 = io.StringIO()
        with redirect_stdout(buf2):
            rc2 = worktree.cmd_path(Args(root=self.repo, branch="feat/list"))
        self.assertEqual(rc2, 0)
        # git 输出用 / 分隔，os.path.join 在 Windows 上是 \，比较前归一化
        self.assertEqual(os.path.normpath(buf2.getvalue().strip()),
                         os.path.normpath(target))

    def test_path_unknown_branch(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = worktree.cmd_path(Args(root=self.repo, branch="nope"))
        self.assertEqual(rc, 1)

    def test_remove_blocked_by_dirty_worktree(self):
        """有未提交改动不让删——删了就没了"""
        target = os.path.join(self.tmp, "wt-dirty")
        with redirect_stdout(io.StringIO()):
            worktree.cmd_create(Args(root=self.repo, branch="feat/dirty",
                                     base="main", dir=target))
        with open(os.path.join(target, "b.txt"), "w", encoding="utf-8") as f:
            f.write("dirty\n")
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = worktree.cmd_remove(Args(root=self.repo, branch="feat/dirty"))
        self.assertEqual(rc, 1)
        self.assertIn("未提交", err.getvalue())
        self.assertTrue(os.path.isdir(target), "被阻断却还是删了")

    def test_remove_force(self):
        target = os.path.join(self.tmp, "wt-force")
        with redirect_stdout(io.StringIO()):
            worktree.cmd_create(Args(root=self.repo, branch="feat/force",
                                     base="main", dir=target))
        with open(os.path.join(target, "b.txt"), "w", encoding="utf-8") as f:
            f.write("dirty\n")
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = worktree.cmd_remove(Args(root=self.repo, branch="feat/force",
                                          force=True, drop_branch=True))
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertFalse(os.path.isdir(target))

    def test_remove_unknown_branch(self):
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = worktree.cmd_remove(Args(root=self.repo, branch="nope"))
        self.assertEqual(rc, 1)

    def test_non_git_repo(self):
        plain = os.path.join(self.tmp, "plain")
        os.makedirs(plain, exist_ok=True)
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            rc = worktree.cmd_list(Args(root=plain))
        self.assertEqual(rc, 1)

    def test_prune(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = worktree.cmd_prune(Args(root=self.repo))
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
