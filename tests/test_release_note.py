#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""release_note.py 单元测试

验证:
- SEMVER 校验与 bump(major/minor/patch)
- collect_closed_bugs 只收集关联当前版本的关闭缺陷
- 重复打版拒绝
- CHANGELOG 生成与插入顺序
- rollback 标记 rolled_back
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import release_note


def make_root():
    tmp = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmp, ".git"), exist_ok=True)
    os.makedirs(os.path.join(tmp, ".lunyu"), exist_ok=True)
    return tmp


def make_args(root, **kw):
    class A:
        pass
    a = A()
    a.root = root
    a.version = None
    a.branch = None
    a.baseline = None
    a.summary = ""
    a.changes = []
    a.confirm = False
    for k, v in kw.items():
        setattr(a, k, v)
    return a


class BumpTest(unittest.TestCase):
    def test_bump_patch(self):
        self.assertEqual(release_note.bump("1.2.3", "patch"), "1.2.4")

    def test_bump_minor(self):
        self.assertEqual(release_note.bump("1.2.3", "minor"), "1.3.0")

    def test_bump_major(self):
        self.assertEqual(release_note.bump("1.2.3", "major"), "2.0.0")

    def test_bump_invalid(self):
        self.assertIsNone(release_note.bump("v1.2.3", "patch"))
        self.assertIsNone(release_note.bump("1.2", "patch"))
        self.assertIsNone(release_note.bump("abc", "patch"))


class CollectBugsTest(unittest.TestCase):
    def test_collect_only_matching_version(self):
        root = make_root()
        with open(os.path.join(root, ".lunyu", "bugs.json"), "w", encoding="utf-8") as f:
            json.dump({"bugs": [
                {"id": "BUG-0001", "status": "关闭", "priority": "P1",
                 "related_version": "v1.2.0", "title": "a"},
                {"id": "BUG-0002", "status": "关闭", "priority": "P2",
                 "related_version": "v1.1.0", "title": "b"},
                {"id": "BUG-0003", "status": "关闭", "priority": "P3",
                 "related_version": "", "title": "c"},
                {"id": "BUG-0004", "status": "新建", "priority": "P1",
                 "related_version": "v1.2.0", "title": "d"},
            ]}, f, ensure_ascii=False)
        bugs = release_note.collect_closed_bugs(root, "1.2.0")
        ids = [b["id"] for b in bugs]
        self.assertEqual(ids, ["BUG-0001"])

    def test_version_match_not_substring(self):
        """回归: 版本必须精确匹配(去 v 前缀), 子串匹配会把 v1.2.0 命中 v11.2.0 的缺陷。"""
        root = make_root()
        with open(os.path.join(root, ".lunyu", "bugs.json"), "w", encoding="utf-8") as f:
            json.dump({"bugs": [
                {"id": "B1", "status": "关闭", "priority": "P1",
                 "related_version": "v11.2.0", "title": "wrong"},
                {"id": "B2", "status": "关闭", "priority": "P1",
                 "related_version": "v1.2.0", "title": "right-v"},
                {"id": "B3", "status": "关闭", "priority": "P1",
                 "related_version": "1.2.0", "title": "right-plain"},
            ]}, f, ensure_ascii=False)
        bugs = release_note.collect_closed_bugs(root, "1.2.0")
        self.assertEqual([b["id"] for b in bugs], ["B2", "B3"])

    def test_missing_bugs_file(self):
        root = make_root()
        self.assertEqual(release_note.collect_closed_bugs(root, "1.0.0"), [])

    def test_open_blockers(self):
        root = make_root()
        with open(os.path.join(root, ".lunyu", "bugs.json"), "w", encoding="utf-8") as f:
            json.dump({"bugs": [
                {"id": "B1", "priority": "P0", "status": "新建"},
                {"id": "B2", "priority": "P1", "status": "关闭"},
                {"id": "B3", "priority": "P2", "status": "新建"},
            ]}, f, ensure_ascii=False)
        blockers = release_note.open_blockers(root)
        self.assertEqual([b["id"] for b in blockers], ["B1"])


class TagTest(unittest.TestCase):
    def test_duplicate_version_rejected(self):
        root = make_root()
        spath = os.path.join(root, ".lunyu", "releases.json")
        with open(spath, "w", encoding="utf-8") as f:
            json.dump({"releases": [
                {"version": "1.0.0", "tag": "v1.0.0", "branch": "main",
                 "created_at": "2026-10-01 00:00:00"},
            ]}, f, ensure_ascii=False)
        # 模拟 git 返回
        with patch.object(release_note, "run_git", return_value=(0, "main", "")), \
             patch.object(release_note, "check_dirty", return_value=False):
            with self.assertRaises(SystemExit) as ctx:
                release_note.cmd_tag(make_args(root, version="1.0.0"))
            self.assertEqual(ctx.exception.code, 1)

    def test_tag_creates_record_and_changelog(self):
        root = make_root()
        with patch.object(release_note, "run_git", side_effect=[
            (0, "dev", ""),   # branch
            (0, "abc1234", ""),  # commit
        ]), patch.object(release_note, "check_dirty", return_value=False):
            release_note.cmd_tag(make_args(root, version="1.0.0",
                                           summary="首个版本", changes=["支持日报"]))
        # releases.json
        with open(os.path.join(root, ".lunyu", "releases.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data["releases"]), 1)
        rec = data["releases"][0]
        self.assertEqual(rec["version"], "1.0.0")
        self.assertEqual(rec["tag"], "v1.0.0")
        self.assertEqual(rec["branch"], "dev")
        self.assertFalse(rec["rolled_back"])
        # CHANGELOG.md
        cl_path = os.path.join(root, "CHANGELOG.md")
        self.assertTrue(os.path.exists(cl_path))
        with open(cl_path, encoding="utf-8") as f:
            cl = f.read()
        self.assertIn("## [1.0.0]", cl)
        self.assertIn("首个版本", cl)
        self.assertIn("支持日报", cl)

    def test_rollback_confirm_marks(self):
        root = make_root()
        with open(os.path.join(root, ".lunyu", "releases.json"), "w", encoding="utf-8") as f:
            json.dump({"releases": [
                {"version": "0.1.0", "tag": "v0.1.0", "branch": "main",
                 "commit": "aaaa", "created_at": "2026-09-01 00:00:00",
                 "rolled_back": False, "closed_bugs": []},
                {"version": "0.2.0", "tag": "v0.2.0", "branch": "main",
                 "commit": "bbbb", "created_at": "2026-09-02 00:00:00",
                 "rolled_back": False, "closed_bugs": []},
            ]}, f, ensure_ascii=False)
        release_note.cmd_rollback(make_args(root, version="0.2.0", confirm=True))
        with open(os.path.join(root, ".lunyu", "releases.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertTrue(data["releases"][1]["rolled_back"])

    def test_rollback_missing_exit1(self):
        root = make_root()
        with self.assertRaises(SystemExit):
            release_note.cmd_rollback(make_args(root, version="9.9.9"))


if __name__ == "__main__":
    unittest.main()