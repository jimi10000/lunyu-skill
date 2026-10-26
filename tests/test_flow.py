#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flow.py 单元测试

用真实临时 git 仓库验证通道判定逻辑:
- 小改动 -> fast
- 中等改动 -> standard
- 大改动/敏感路径 -> full
- 文档/测试专属改动 -> fast
"""
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import flow


def git(root, *args):
    r = subprocess.run(["git"] + list(args), cwd=root, capture_output=True,
                       text=True, errors="ignore")
    return r.returncode, r.stdout


def make_repo(files):
    """创建临时 git 仓库并写入指定文件 {相对路径: 内容}。"""
    tmp = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.name", "tester"], cwd=tmp, check=True)
    for path, content in files.items():
        p = os.path.join(tmp, path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
    subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp, check=True)
    return tmp


class ClassifyTest(unittest.TestCase):
    def test_small_change_fast(self):
        files = {"src/a.py": (5, 2)}
        tier, reason, lines, n = flow.classify(files)
        self.assertEqual(tier, "fast")
        self.assertEqual(lines, 7)
        self.assertEqual(n, 1)

    def test_medium_change_standard(self):
        files = {f"src/m{i}.py": (10, 5) for i in range(3)}
        tier, _, _, _ = flow.classify(files)
        self.assertEqual(tier, "standard")

    def test_large_change_full(self):
        files = {f"src/big{i}.py": (100, 100) for i in range(9)}
        tier, _, _, _ = flow.classify(files)
        self.assertEqual(tier, "full")

    def test_many_lines_full(self):
        files = {"src/one.py": (500, 0)}
        tier, _, _, _ = flow.classify(files)
        self.assertEqual(tier, "full")

    def test_doc_only_fast(self):
        files = {"README.md": (10, 0), "docs/guide.md": (5, 0)}
        tier, reason, _, _ = flow.classify(files)
        self.assertEqual(tier, "fast")
        self.assertIn("文档", reason)

    def test_test_only_fast(self):
        files = {"tests/test_a.py": (20, 0), "src/a_test.py": (5, 0)}
        tier, reason, _, _ = flow.classify(files)
        self.assertEqual(tier, "fast")
        self.assertIn("测试", reason)

    def test_sensitive_path_full(self):
        files = {".env": (2, 0)}
        tier, reason, _, _ = flow.classify(files)
        self.assertEqual(tier, "full")
        self.assertIn("敏感", reason)

    def test_auth_path_full(self):
        files = {"src/auth/login.py": (3, 0)}
        tier, _, _, _ = flow.classify(files)
        self.assertEqual(tier, "full")

    def test_sql_full(self):
        files = {"db/migrate.sql": (1, 0)}
        tier, _, _, _ = flow.classify(files)
        self.assertEqual(tier, "full")


class RealGitTest(unittest.TestCase):
    def test_parse_numstat_and_classify_fast(self):
        repo = make_repo({"README.md": "hello\n"})
        # 修改 1 个文件 1 行 -> fast
        with open(os.path.join(repo, "README.md"), "a", encoding="utf-8") as f:
            f.write("more\n")
        files = flow.parse_numstat(repo, ["diff"])
        self.assertIn("README.md", files)
        tier, _, _, _ = flow.classify(files)
        self.assertEqual(tier, "fast")

    def test_untracked_new_file_counted(self):
        repo = make_repo({"README.md": "x\n"})
        with open(os.path.join(repo, "note.md"), "w", encoding="utf-8") as f:
            f.write("line1\nline2\n")
        files = flow.parse_numstat(repo, ["diff"])
        self.assertIn("note.md", files)
        self.assertEqual(files["note.md"], (2, 0))

    def test_get_diff_args_no_head_fallback(self):
        # 刚 init 无提交 -> 回退 git diff 而不是 diff HEAD
        tmp = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        class A:
            staged = False
            range = None
            path = tmp
        args = flow.get_diff_args(A())
        self.assertEqual(args, ["diff"])

    def test_steps_and_checklists_integrity(self):
        self.assertIn("fast", flow.STEPS)
        self.assertIn("standard", flow.STEPS)
        self.assertIn("full", flow.STEPS)
        for tier in ("fast", "standard", "full"):
            self.assertIn("steps", flow.STEPS[tier])
            self.assertIn("must", flow.STEPS[tier])
            self.assertIn("skip", flow.STEPS[tier])
            self.assertIn(tier, flow.CHECKLISTS)


if __name__ == "__main__":
    unittest.main()