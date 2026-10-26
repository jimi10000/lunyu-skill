# -*- coding: utf-8 -*-
"""patrol.py 单元测试（自驱力层）。

重点覆盖：
  - 各检查项的"有/无"判定（不能误报，也不能漏报）
  - 阻断项识别（P0/P1 未关闭）
  - 结果按阻断程度排序（blocking 必须排最前）
  - 退出码语义：有阻断项 -> 1
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import patrol  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.lunyu = os.path.join(self.root, ".lunyu")
        os.makedirs(self.lunyu, exist_ok=True)

    def write_bugs(self, bugs):
        with open(os.path.join(self.lunyu, "bugs.json"), "w", encoding="utf-8") as f:
            json.dump({"next_id": len(bugs) + 1, "bugs": bugs}, f, ensure_ascii=False)

    def write_releases(self, rels):
        with open(os.path.join(self.lunyu, "releases.json"), "w", encoding="utf-8") as f:
            json.dump({"releases": rels}, f, ensure_ascii=False)

    def write_lessons(self, lessons):
        with open(os.path.join(self.lunyu, "lessons.json"), "w", encoding="utf-8") as f:
            json.dump({"next_id": len(lessons) + 1, "lessons": lessons}, f, ensure_ascii=False)

    @staticmethod
    def days_ago(n):
        return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")


class BlockingBugsTest(Base):
    def test_open_p0_is_blocking(self):
        self.write_bugs([{"id": "BUG-0001", "title": "崩溃", "priority": "P0", "status": "新建"}])
        r = patrol.check_blocking_bugs(self.root)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "blocking")

    def test_closed_p0_not_blocking(self):
        self.write_bugs([{"id": "BUG-0001", "title": "崩溃", "priority": "P0", "status": "关闭"}])
        self.assertIsNone(patrol.check_blocking_bugs(self.root))

    def test_p2_open_not_blocking(self):
        """P2/P3 未关闭不算阻断，避免门禁过严。"""
        self.write_bugs([{"id": "BUG-0002", "title": "小问题", "priority": "P2", "status": "新建"}])
        self.assertIsNone(patrol.check_blocking_bugs(self.root))

    def test_empty_ledger_no_crash(self):
        self.assertIsNone(patrol.check_blocking_bugs(self.root))


class OverdueTest(Base):
    def test_old_open_bug_flagged(self):
        self.write_bugs([{"id": "BUG-0001", "title": "老缺陷", "priority": "P2",
                          "status": "新建", "created_at": self.days_ago(60)}])
        r = patrol.check_overdue_bugs(self.root, 14)
        self.assertIsNotNone(r)
        self.assertIn("已挂 60 天", r[2])

    def test_fresh_bug_not_flagged(self):
        self.write_bugs([{"id": "BUG-0001", "title": "新缺陷", "priority": "P2",
                          "status": "新建", "created_at": self.days_ago(2)}])
        self.assertIsNone(patrol.check_overdue_bugs(self.root, 14))

    def test_closed_old_bug_not_flagged(self):
        self.write_bugs([{"id": "BUG-0001", "title": "已修", "priority": "P2",
                          "status": "关闭", "created_at": self.days_ago(60)}])
        self.assertIsNone(patrol.check_overdue_bugs(self.root, 14))


class ReportTest(Base):
    def test_missing_daily_report_flagged(self):
        r = patrol.check_missing_report(self.root)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "medium")

    def test_written_daily_report_not_flagged(self):
        today = datetime.now().strftime("%Y-%m-%d")
        d = os.path.join(self.lunyu, "reports")
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "日报-%s.md" % today), "w", encoding="utf-8").write("x")
        iso = datetime.now().isocalendar()
        open(os.path.join(d, "周报-%d-%02d.md" % (iso[0], iso[1])), "w", encoding="utf-8").write("x")
        self.assertIsNone(patrol.check_missing_report(self.root))


class ChangelogTest(Base):
    def test_missing_changelog_file(self):
        self.write_releases([{"version": "2.0.0"}])
        r = patrol.check_changelog_behind(self.root)
        self.assertIsNotNone(r)

    def test_changelog_behind_version(self):
        self.write_releases([{"version": "2.0.0"}])
        with open(os.path.join(self.root, "CHANGELOG.md"), "w", encoding="utf-8") as f:
            f.write("# Changelog\n\n## [1.0.0]\n")
        r = patrol.check_changelog_behind(self.root)
        self.assertIsNotNone(r)
        self.assertIn("2.0.0", r[2])

    def test_changelog_up_to_date(self):
        self.write_releases([{"version": "2.0.0"}])
        with open(os.path.join(self.root, "CHANGELOG.md"), "w", encoding="utf-8") as f:
            f.write("# Changelog\n\n## [2.0.0]\n")
        self.assertIsNone(patrol.check_changelog_behind(self.root))

    def test_no_releases_no_noise(self):
        """没有发过版本就不该催 CHANGELOG。"""
        self.assertIsNone(patrol.check_changelog_behind(self.root))


class LessonsStaleTest(Base):
    def test_empty_lessons_flagged(self):
        r = patrol.check_lessons_stale(self.root, 30)
        self.assertIsNotNone(r)
        self.assertIn("经验库为空", r[1])

    def test_recent_lesson_not_flagged(self):
        self.write_lessons([{"id": "L-0001", "date": datetime.now().strftime("%Y-%m-%d")}])
        self.assertIsNone(patrol.check_lessons_stale(self.root, 30))

    def test_stale_lesson_flagged(self):
        old = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        self.write_lessons([{"id": "L-0001", "date": old}])
        r = patrol.check_lessons_stale(self.root, 30)
        self.assertIsNotNone(r)
        self.assertIn("90", r[2])


class OrderAndExitCodeTest(Base):
    def test_blocking_sorted_first(self):
        """阻断项必须排最前，否则会被提醒项淹没。"""
        self.write_bugs([
            {"id": "BUG-0001", "priority": "P0", "status": "新建",
             "title": "崩溃", "created_at": self.days_ago(60)},
        ])
        results = patrol.run_checks(self.root, 14, 30)
        self.assertTrue(results)
        self.assertEqual(results[0][0], "blocking")

    def test_exit_code_1_when_blocking(self):
        self.write_bugs([{"id": "BUG-0001", "priority": "P1", "status": "新建", "title": "严重"}])
        with patch.object(patrol, "find_root", return_value=self.root):
            rc = patrol.main(["--root", self.root])
        self.assertEqual(rc, 1)

    def test_exit_code_0_when_clean(self):
        """干净项目（无缺陷、报告齐全、无版本记录）应返回 0。"""
        today = datetime.now().strftime("%Y-%m-%d")
        d = os.path.join(self.lunyu, "reports")
        os.makedirs(d, exist_ok=True)
        iso = datetime.now().isocalendar()
        open(os.path.join(d, "日报-%s.md" % today), "w", encoding="utf-8").write("x")
        open(os.path.join(d, "周报-%d-%02d.md" % (iso[0], iso[1])), "w", encoding="utf-8").write("x")
        self.write_lessons([{"id": "L-0001", "date": today}])
        rc = patrol.main(["--root", self.root])
        self.assertEqual(rc, 0)

    def test_single_check_failure_does_not_crash_patrol(self):
        """某一项检查炸了，巡检整体仍要跑完（自驱力不能自己先趴下）。"""
        with patch.object(patrol, "check_blocking_bugs", side_effect=RuntimeError("boom")):
            results = patrol.run_checks(self.root, 14, 30)
        self.assertIsInstance(results, list)

    def test_json_output(self):
        self.write_bugs([{"id": "BUG-0001", "priority": "P0", "status": "新建", "title": "崩溃"}])
        rc = patrol.main(["--root", self.root, "--json"])
        self.assertEqual(rc, 1)


class ParseDateTest(unittest.TestCase):
    def test_various_formats(self):
        self.assertIsNotNone(patrol.parse_date("2026-10-26"))
        self.assertIsNotNone(patrol.parse_date("2026-10-26 23:00:00"))
        self.assertIsNotNone(patrol.parse_date("2026/10/26"))

    def test_invalid_returns_none(self):
        self.assertIsNone(patrol.parse_date(""))
        self.assertIsNone(patrol.parse_date(None))
        self.assertIsNone(patrol.parse_date("不是日期"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
