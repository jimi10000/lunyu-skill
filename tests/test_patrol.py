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

    def write_report(self, name, content):
        """往 .lunyu/reports/ 下写一份报告。"""
        d = os.path.join(self.lunyu, "reports")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            f.write(content)

    def write_raw(self, rel_path, content):
        """写任意文件（含非法 JSON，用来验证容错）。"""
        p = os.path.join(self.lunyu, rel_path)
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

    @staticmethod
    def date_offset(n):
        return (datetime.now() - timedelta(days=n)).strftime("%Y-%m-%d")

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

    def test_warning_checks_do_not_block(self):
        """CR 未闭环 / 复盘待办 / 昨日计划 属于警告与提醒，不该把门禁拉红。"""
        self.write_raw("reviews.json", json.dumps({"reviews": [
            {"comments": [{"title": "补边界用例", "status": "新建"}]},
        ]}))
        self.write_report("summary_2026-01-01.md", "- [ ] 补并发压测\n")
        self.write_report("日报-%s.md" % self.date_offset(1),
                          "## 明日计划\n- 重构登录模块\n")
        rc = patrol.main(["--root", self.root])
        self.assertEqual(rc, 0)


class YesterdayPlanTest(Base):
    """昨日「明日计划」未兑现 —— 判定要宽松，宁可少报不可误报。"""

    def write_yesterday(self, plan_body):
        self.write_report("日报-%s.md" % self.date_offset(1),
                          "# 日报\n\n## 今日完成\n- x\n\n## 明日计划\n%s\n" % plan_body)

    def test_no_yesterday_report_skipped(self):
        """没有昨天的日报就没得比对，静默跳过。"""
        self.assertIsNone(patrol.check_yesterday_plan_unfulfilled(self.root))

    def test_placeholder_plan_not_flagged(self):
        """「（待补充）」这类占位条目不该被当成没兑现。"""
        self.write_yesterday("- （待补充）")
        self.assertIsNone(patrol.check_yesterday_plan_unfulfilled(self.root))

    def test_unfulfilled_plan_flagged(self):
        self.write_yesterday("- 重构登录模块")
        self.write_report("日报-%s.md" % self.date_offset(0), "今天主要是摸鱼")
        r = patrol.check_yesterday_plan_unfulfilled(self.root)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "low")
        self.assertIn("重构登录模块", r[2])

    def test_fulfilled_in_today_report_not_flagged(self):
        """今天的日报里出现了同一件事，就算兑现。"""
        self.write_yesterday("- 重构登录模块")
        self.write_report("日报-%s.md" % self.date_offset(0),
                          "今天完成了重构登录模块的拆分")
        self.assertIsNone(patrol.check_yesterday_plan_unfulfilled(self.root))

    def test_fulfilled_by_lessons_not_flagged(self):
        """宽松匹配：经验库里沾上关键词也算数。"""
        self.write_yesterday("- 重构登录模块")
        self.write_lessons([{"id": "L-0001", "scene": "登录模块重构踩坑",
                             "solution": "先抽接口", "date": self.date_offset(0)}])
        self.assertIsNone(patrol.check_yesterday_plan_unfulfilled(self.root))

    def test_garbage_report_no_crash(self):
        """日报内容乱七八糟也不能让巡检崩。"""
        self.write_report("日报-%s.md" % self.date_offset(1), "\x00\xff 乱码 ## 明日计划\n*  ")
        self.assertIsNone(patrol.check_yesterday_plan_unfulfilled(self.root))

    def test_plan_items_extracts_only_plan_section(self):
        content = "# 日报\n## 今日完成\n- 写单测\n## 明日计划\n- 补压测\n"
        self.assertEqual(patrol.plan_items(content), ["补压测"])

    def test_keywords_splits_chinese_bigram(self):
        kws = patrol.keywords("重构登录模块")
        self.assertIn("登录", kws)
        self.assertIn("模块", kws)


class CrCommentsTest(Base):
    def test_missing_reviews_file_skipped(self):
        self.assertIsNone(patrol.check_open_cr_comments(self.root))

    def test_open_comments_flagged(self):
        self.write_raw("reviews.json", json.dumps({"reviews": [
            {"comments": [{"title": "补边界用例", "status": "新建"}]},
        ]}))
        r = patrol.check_open_cr_comments(self.root)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "medium")
        self.assertIn("补边界用例", r[2])

    def test_closed_comments_not_flagged(self):
        self.write_raw("reviews.json", json.dumps({"reviews": [
            {"comments": [{"title": "补边界用例", "status": "已闭环"},
                          {"title": "改名", "closed": True}]},
        ]}))
        self.assertIsNone(patrol.check_open_cr_comments(self.root))

    def test_list_format_supported(self):
        """reviews.json 也允许直接是意见数组。"""
        self.write_raw("reviews.json", json.dumps(
            [{"title": "拆函数", "status": "未处理"}]))
        r = patrol.check_open_cr_comments(self.root)
        self.assertIsNotNone(r)
        self.assertIn("1 条", r[2])

    def test_broken_json_no_crash(self):
        self.write_raw("reviews.json", "{坏掉的 json")
        self.assertIsNone(patrol.check_open_cr_comments(self.root))


class ReviewTodosTest(Base):
    def test_no_reports_dir_skipped(self):
        self.assertIsNone(patrol.check_review_todos(self.root))

    def test_unchecked_todos_flagged(self):
        self.write_report("summary_2026-01-01.md",
                          "## 下轮待办\n- [ ] 补并发压测\n- [x] 建立模板\n")
        r = patrol.check_review_todos(self.root)
        self.assertIsNotNone(r)
        self.assertEqual(r[0], "medium")
        self.assertIn("补并发压测", r[2])

    def test_all_done_not_flagged(self):
        self.write_report("summary_2026-01-01.md", "- [x] 补并发压测\n")
        self.assertIsNone(patrol.check_review_todos(self.root))

    def test_non_summary_files_ignored(self):
        """日报/周报里的 checkbox 不算复盘待办。"""
        self.write_report("日报-2026-01-01.md", "- [ ] 补压测\n")
        self.assertIsNone(patrol.check_review_todos(self.root))


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
