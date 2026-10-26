# -*- coding: utf-8 -*-
"""lessons.py 单元测试（自学习层）。

重点覆盖：
  - 检索打分：标签权重 > 场景 > 问题 > 结论
  - 命中即加权：search 命中后 hits 自增（越用越靠前，这是"学习"的核心行为）
  - add 编号递增与字段落盘
  - 中文 2-gram 分词能命中短语
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import lessons  # noqa: E402


def make_item(lid, scene, problem, solution, tags, kind="结论", hits=0):
    return {
        "id": lid, "scene": scene, "problem": problem, "solution": solution,
        "tags": tags, "kind": kind, "hits": hits, "date": "2026-10-26",
    }


class TokenizeTest(unittest.TestCase):
    def test_english_and_digits(self):
        t = lessons.tokenize("Android 8155 broadcast")
        self.assertIn("android", t)
        self.assertIn("8155", t)
        self.assertIn("broadcast", t)

    def test_chinese_bigram(self):
        """中文靠 2-gram 命中短语，'车机广播' 应切出 '车机'/'机广'/'广播'。"""
        t = lessons.tokenize("车机广播")
        self.assertIn("车机", t)
        self.assertIn("广播", t)


class ScoreTest(unittest.TestCase):
    def test_tag_weight_highest(self):
        it = make_item("L-1", "某场景", "", "某结论", ["车机"])
        with_tag = lessons.score(it, lessons.tokenize("车机"))
        no_tag = lessons.score(make_item("L-2", "某场景", "", "某结论", []), lessons.tokenize("车机"))
        self.assertGreater(with_tag, no_tag)

    def test_scene_beats_solution(self):
        in_scene = lessons.score(make_item("L-1", "车机", "", "无关", []), lessons.tokenize("车机"))
        in_solution = lessons.score(make_item("L-2", "无关", "", "车机", []), lessons.tokenize("车机"))
        self.assertGreater(in_scene, in_solution)

    def test_zero_for_unrelated(self):
        it = make_item("L-1", "苹果种植", "", "浇水", ["农业"])
        self.assertEqual(lessons.score(it, lessons.tokenize("车机广播")), 0.0)

    def test_hits_boosts_score(self):
        """热门经验小幅加权，用得越多越靠前。"""
        cold = lessons.score(make_item("L-1", "车机", "", "x", ["车机"], hits=0), lessons.tokenize("车机"))
        hot = lessons.score(make_item("L-2", "车机", "", "x", ["车机"], hits=10), lessons.tokenize("车机"))
        self.assertGreater(hot, cold)


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.items = [
            make_item("L-0001", "车机静态广播不分发", "manifest 被忽略", "动态注册兜底", ["android", "车机", "广播"], "踩坑"),
            make_item("L-0002", "交付必须带安装包", "", "附 APK + md5", ["交付"], "偏好"),
            make_item("L-0003", "苹果种植", "", "浇水", ["农业"], "结论"),
        ]

    def test_search_ranks_most_relevant_first(self):
        res = lessons.search_items(self.items, "车机广播")
        self.assertEqual(res[0]["id"], "L-0001")

    def test_search_excludes_unrelated(self):
        res = lessons.search_items(self.items, "车机广播")
        self.assertNotIn("L-0003", [r["id"] for r in res])

    def test_search_respects_top(self):
        res = lessons.search_items(self.items, "车机", top=1)
        self.assertEqual(len(res), 1)

    def test_empty_query_returns_nothing(self):
        self.assertEqual(lessons.search_items(self.items, ""), [])


class CmdTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = self.tmp

    def _data(self):
        with open(os.path.join(self.root, ".lunyu", "lessons.json"), encoding="utf-8") as f:
            return json.load(f)

    def _args(self, **kw):
        class A:
            pass
        a = A()
        a.root = self.root
        for k, v in kw.items():
            setattr(a, k, v)
        return a

    def test_add_increments_id(self):
        lessons.cmd_add(self._args(scene="场景A", solution="结论A", problem="",
                                   tags="a,b", kind="结论", source=""))
        lessons.cmd_add(self._args(scene="场景B", solution="结论B", problem="",
                                   tags="", kind="踩坑", source=""))
        d = self._data()
        self.assertEqual([it["id"] for it in d["lessons"]], ["L-0001", "L-0002"])
        self.assertEqual(d["next_id"], 3)

    def test_add_splits_tags(self):
        lessons.cmd_add(self._args(scene="s", solution="x", problem="",
                                   tags="android, 车机 ,广播", kind="结论", source=""))
        self.assertEqual(self._data()["lessons"][0]["tags"], ["android", "车机", "广播"])

    def test_search_increments_hits(self):
        """核心自学习行为：命中一次，hits +1。"""
        lessons.cmd_add(self._args(scene="车机静态广播", solution="动态注册", problem="",
                                   tags="车机,广播", kind="踩坑", source=""))
        a = self._args(query="车机广播", top=5)
        lessons.cmd_search(a)
        self.assertEqual(self._data()["lessons"][0]["hits"], 1)
        lessons.cmd_search(self._args(query="车机广播", top=5))
        self.assertEqual(self._data()["lessons"][0]["hits"], 2)

    def test_search_no_match_does_not_increment(self):
        lessons.cmd_add(self._args(scene="车机", solution="x", problem="", tags="车机", kind="结论", source=""))
        lessons.cmd_search(self._args(query="苹果种植", top=5))
        self.assertEqual(self._data()["lessons"][0]["hits"], 0)

    def test_list_filters_by_tag(self):
        lessons.cmd_add(self._args(scene="a", solution="x", problem="", tags="车机", kind="结论", source=""))
        lessons.cmd_add(self._args(scene="b", solution="y", problem="", tags="农业", kind="结论", source=""))
        self.assertEqual(lessons.cmd_list(self._args(tag="车机", kind=None)), 0)

    def test_export_writes_markdown(self):
        lessons.cmd_add(self._args(scene="场景", solution="结论", problem="",
                                   tags="t", kind="结论", source=""))
        out = os.path.join(self.tmp, "out.md")
        lessons.cmd_export(self._args(out=out))
        content = open(out, encoding="utf-8").read()
        self.assertIn("L-0001", content)
        self.assertIn("经验库导出", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
