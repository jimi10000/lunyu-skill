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
from io import StringIO
from contextlib import redirect_stdout

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


def write_report(root, name, text):
    p = os.path.join(root, ".lunyu", "reports", name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
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


DAILY_TPL = """# 日报：{d}

## 今日完成
- 完成 {tag} 功能

## 今日数据
- 缺陷台账：无

## 明日计划
- 推进 {tag} 联调

## 风险与阻塞
- 无
"""

RETRO_TPL = """# 日报：{d}

## 今日完成
- 今日产出 {tag}

## 收获
- 沉淀了 {tag} 的排错套路

## 失误与改进
- 忘了回归，下次先跑测试再提测

## 明日计划
- 补齐 {tag} 用例
"""


class AggregateTest(unittest.TestCase):
    """周报聚合本周日报 / 总结聚合周报"""

    def setUp(self):
        self.cwd = os.getcwd()
        self.root = make_project()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.cwd)

    def run_gen(self, fn, *a, **kw):
        buf = StringIO()
        with redirect_stdout(buf):
            content, fname = fn(*a, **kw)
        return content, fname, buf.getvalue()

    def test_extract_sections(self):
        secs = report.extract_sections(DAILY_TPL.format(d="2026-10-27", tag="登录"))
        self.assertIn("完成 登录 功能", secs["收获"])
        self.assertIn("推进 登录 联调", secs["明日计划"])
        self.assertEqual(secs["失误与改进"], [])
        # 占位符不应被聚合
        self.assertNotIn("无", secs["明日计划"])

    def test_weekly_aggregates_this_week_dailies(self):
        # 本周：周一(10-26) 周二(10-27)；上周：10-18 应被忽略
        for d, tag in [("2026-10-26", "周一"), ("2026-10-27", "周二"), ("2026-10-18", "上周")]:
            write_report(self.root, f"日报-{d}.md", DAILY_TPL.format(d=d, tag=tag))
        content, _, hint = self.run_gen(report.gen_weekly, "项目X", "me",
                                        ["本周手写内容"], "2026-10-26")
        self.assertIn("（自动聚合自本周日报）", content)
        self.assertIn("[日报-2026-10-26] 完成 周一 功能", content)
        self.assertIn("[日报-2026-10-27] 推进 周二 联调", content)
        self.assertNotIn("上周", content)
        # 用户手写在前，聚合在后
        self.assertLess(content.index("本周手写内容"),
                        content.index("（自动聚合自本周日报）"))
        self.assertIn("已合并本周 2 篇日报", hint)

    def test_weekly_aggregates_retro_sections(self):
        write_report(self.root, "日报-2026-10-27.md",
                     RETRO_TPL.format(d="2026-10-27", tag="支付"))
        content, _, _ = self.run_gen(report.gen_weekly, "项目X", "me", [], "2026-10-26")
        gain_idx = content.index("（自动聚合自本周日报）收获")
        loss_idx = content.index("（自动聚合自本周日报）失误与改进")
        plan_idx = content.index("（自动聚合自本周日报）明日计划")
        # 分别落在 本周完成 / 风险与阻塞 / 下周计划 章节内
        self.assertLess(content.index("## 本周完成"), gain_idx)
        self.assertLess(gain_idx, content.index("## 本周数据"))
        self.assertLess(content.index("## 风险与阻塞"), loss_idx)
        self.assertLess(content.index("## 下周计划"), plan_idx)
        self.assertIn("忘了回归，下次先跑测试再提测", content)

    def test_weekly_without_dailies(self):
        content, _, hint = self.run_gen(report.gen_weekly, "项目X", "me",
                                        ["本周手写内容"], "2026-10-26")
        self.assertNotIn("（自动聚合自本周日报）", content)
        self.assertIn("本周（", hint)
        self.assertIn("无日报", hint)

    def test_weekly_no_agg_flag(self):
        write_report(self.root, "日报-2026-10-27.md",
                     DAILY_TPL.format(d="2026-10-27", tag="登录"))
        content, _, _ = self.run_gen(report.gen_weekly, "项目X", "me",
                                     ["本周手写内容"], "2026-10-26", agg=False)
        self.assertNotIn("（自动聚合自本周日报）", content)
        self.assertNotIn("完成 登录 功能", content)

    def test_summary_aggregates_weeklies(self):
        write_report(self.root, "周报-2026-10-19.md", """# 周报：2026-10-13 ~ 2026-10-19

## 本周完成
- 打通 CI 流水线

## 下周计划
- 接入产物归档
""")
        content, fname, hint = self.run_gen(report.gen_summary, "项目X", "me", ["核心成果"])
        self.assertEqual(fname, f"项目总结-{date.today().strftime('%Y%m%d')}.md")
        self.assertIn("（自动聚合自周报）", content)
        self.assertIn("[周报-2026-10-19] 打通 CI 流水线", content)
        self.assertLess(content.index("核心成果"),
                        content.index("（自动聚合自周报）"))
        self.assertIn("已合并 1 篇周报", hint)

    def test_aggregation_is_fault_tolerant(self):
        # 格式不符（无标题）
        write_report(self.root, "日报-2026-10-27.md", "乱七八糟的一段话，没有任何标题\n")
        # 编码异常
        write_report(self.root, "日报-2026-10-28.md", "")
        with open(os.path.join(self.root, ".lunyu", "reports", "日报-2026-10-28.md"),
                  "wb") as f:
            f.write(b"\xff\xfe\x00\x80bad bytes")
        # 同名目录（读取会抛 OSError）
        os.makedirs(os.path.join(self.root, ".lunyu", "reports", "日报-2026-10-29.md"))
        content, _, hint = self.run_gen(report.gen_weekly, "项目X", "me", [], "2026-10-26")
        self.assertIn("# 周报：", content)
        self.assertNotIn("（自动聚合自本周日报）", content)
        self.assertIn("2 篇报告无法读取/格式不符", hint)


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