#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""report.py 单元测试

验证:
- 数据读取: bugs/releases/changelog
- 日期过滤: 今日/本周
- 缺陷汇总: 关闭计数、未关闭 P0/P1、优先级分布
- 报告生成: summary/daily/weekly 含关键章节与文件名
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import report


def make_project():
    tmp = tempfile.mkdtemp()
    lunyu = os.path.join(tmp, ".lunyu")
    os.makedirs(os.path.join(lunyu, "reports"), exist_ok=True)
    return tmp


def write_json(root, rel, data):
    p = os.path.join(root, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return p


class FilterTest(unittest.TestCase):
    def test_filter_by_date(self):
        items = [
            {"date": "2026-10-26"},  # 周一
            {"date": "2026-10-27"},  # 周二
            {"date": "2026-10-18"},  # 上周
        ]
        today, week = report.filter_by_date(items, "2026-10-26")
        self.assertEqual([i["date"] for i in today], ["2026-10-26"])
        self.assertEqual(len(week), 2)

    def test_filter_bad_date(self):
        today, week = report.filter_by_date([{"date": "bad"}], "2026-10-26")
        self.assertEqual(today, [])
        self.assertEqual(week, [])

    def test_filter_empty(self):
        today, week = report.filter_by_date([], "2026-10-26")
        self.assertEqual((today, week), ([], []))


class SummarizeBugsTest(unittest.TestCase):
    def test_summary_counts(self):
        bugs = [
            {"priority": "P0", "status": "关闭", "closed_at": "2026-10-26 09:00:00", "title": "a"},
            {"priority": "P1", "status": "新建", "title": "b"},
            {"priority": "P2", "status": "关闭", "closed_at": "2026-10-27 10:00:00", "title": "c"},
            {"priority": "P3", "status": "关闭", "closed_at": "2026-10-19 10:00:00", "title": "d"},
        ]
        s = report.summarize_bugs(bugs, "2026-10-26")
        self.assertEqual(s["total"], 4)
        self.assertEqual(s["today_closed"], 1)  # 只有 a
        self.assertEqual(s["week_closed"], 2)  # a + c（b 未关闭不计）
        self.assertEqual(s["dist"]["P0"], 1)
        self.assertEqual(len(s["open_p0p1"]), 1)  # b

    def test_summary_when_none(self):
        self.assertIsNone(report.summarize_bugs(None, "2026-10-26"))
        self.assertIsNone(report.summarize_bugs({"bugs": []}, "2026-10-26"))


class SummarizeReleasesTest(unittest.TestCase):
    def test_release_tags(self):
        rel = {"releases": [
            {"version": "1.0.0", "created_at": "2026-10-26 18:00:00"},
            {"version": "1.1.0", "created_at": "2026-10-18 18:00:00"},
        ]}
        s = report.summarize_releases(rel, "2026-10-26")
        self.assertEqual(s["today_tags"], ["1.0.0"])
        self.assertEqual(len(s["week_tags"]), 1)


class GenReportTest(unittest.TestCase):
    def test_gen_summary(self):
        root = make_project()
        os.chdir(root)  # 脚本用相对路径读 .lunyu
        write_json(root, ".lunyu/bugs.json", {"bugs": [
            {"id": "B1", "priority": "P1", "status": "新建", "title": "bug1"},
        ]})
        write_json(root, ".lunyu/releases.json", {"releases": [
            {"version": "1.0.0", "created_at": "2026-10-26 18:00:00"},
        ]})
        content, fname = report.gen_summary("测试项目", "作者", ["完成核心功能"])
        self.assertEqual(fname, f"项目总结-{date.today().strftime('%Y%m%d')}.md")
        self.assertIn("# 项目总结：测试项目", content)
        self.assertIn("作者", content)
        self.assertIn("完成核心功能", content)
        self.assertIn("版本存档", content)
        self.assertIn("缺陷总数", content)

    def test_gen_daily(self):
        root = make_project()
        os.chdir(root)
        write_json(root, ".lunyu/bugs.json", {"bugs": [
            {"id": "B1", "priority": "P2", "status": "关闭",
             "closed_at": "2026-10-26 09:00:00", "title": "fixed"},
        ]})
        content, fname = report.gen_daily("项目X", "me", ["今天完成了A"], "2026-10-26")
        self.assertEqual(fname, "日报-2026-10-26.md")
        self.assertIn("# 日报：2026-10-26", content)
        self.assertIn("今天完成了A", content)
        self.assertIn("今日关闭 1 个", content)
        self.assertIn("明日计划", content)

    def test_gen_weekly(self):
        root = make_project()
        os.chdir(root)
        write_json(root, ".lunyu/releases.json", {"releases": [
            {"version": "2.0.0", "created_at": "2026-10-26 18:00:00"},
        ]})
        content, fname = report.gen_weekly("项目X", "me", ["本周完成B"], "2026-10-26")
        self.assertEqual(fname, "周报-2026-10-26.md")
        self.assertIn("# 周报：", content)
        self.assertIn("本周完成B", content)
        self.assertIn("本周发版：2.0.0", content)
        self.assertIn("下周计划", content)

    def test_esc(self):
        self.assertEqual(report.esc("a\nb"), "a b")


class LoadChangelogTest(unittest.TestCase):
    def test_parse_changelog(self):
        root = make_project()
        os.chdir(root)
        os.makedirs(".lunyu", exist_ok=True)
        with open(".lunyu/CHANGELOG.md", "w", encoding="utf-8") as f:
            f.write("# CHANGELOG\n\n## [1.0.0] - 2026-10-26\n\n- x\n\n## [0.9.0] - 2026-10-01\n")
        entries = report.load_changelog()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["version"], "1.0.0")
        self.assertEqual(entries[0]["date"], "2026-10-26")


if __name__ == "__main__":
    unittest.main()