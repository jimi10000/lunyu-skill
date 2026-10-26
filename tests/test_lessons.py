# -*- coding: utf-8 -*-
"""lessons.py 单元测试（自学习层）。

重点覆盖：
  - 检索打分：标签权重 > 场景 > 问题 > 结论
  - 命中即加权：search 命中后 hits 自增（越用越靠前，这是"学习"的核心行为）
  - add 编号递增与字段落盘
  - 中文 2-gram 分词能命中短语
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from unittest.mock import patch

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
        # 测试隔离：全局库重定向到临时目录，避免污染真实 ~/.lunyu
        gp = patch.object(lessons, "global_store_path",
                          return_value=os.path.join(self.tmp, "global-lessons.json"))
        gp.start()
        self.addCleanup(gp.stop)

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


class SeedTest(unittest.TestCase):
    """种子经验：让项目不从空库起步，且必须幂等。"""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        # 造一个最小技能布局，让 _seed_file() 能定位到 references/
        self.scripts = os.path.join(self.root, "scripts")
        self.refs = os.path.join(self.root, "references")
        os.makedirs(self.scripts)
        os.makedirs(self.refs)
        seed = {
            "lessons": [
                {"kind": "踩坑", "scene": "场景甲", "problem": "p", "solution": "s",
                 "tags": ["a"], "source": "x"},
                {"kind": "结论", "scene": "场景乙", "problem": "", "solution": "s2",
                 "tags": ["b"], "source": ""},
            ]
        }
        with open(os.path.join(self.refs, "seed-lessons.json"), "w", encoding="utf-8") as f:
            json.dump(seed, f, ensure_ascii=False)

    def _seed(self):
        with patch.object(lessons, "_seed_file",
                          return_value=os.path.join(self.refs, "seed-lessons.json")):
            return lessons.cmd_seed(type("A", (), {"root": self.root})())

    def _data(self):
        with open(os.path.join(self.root, ".lunyu", "lessons.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_seed_imports_all(self):
        self.assertEqual(self._seed(), 0)
        self.assertEqual(len(self._data()["lessons"]), 2)

    def test_seed_is_idempotent(self):
        """重复 seed 不能产生重复条目（否则每次跑都翻倍）。"""
        self._seed()
        self._seed()
        scenes = [it["scene"] for it in self._data()["lessons"]]
        self.assertEqual(scenes.count("场景甲"), 1)
        self.assertEqual(len(scenes), 2)

    def test_seed_assigns_ids(self):
        self._seed()
        ids = [it["id"] for it in self._data()["lessons"]]
        self.assertEqual(ids, ["L-0001", "L-0002"])

    def test_seed_missing_file_returns_1(self):
        with patch.object(lessons, "_seed_file", return_value="/nonexistent/x.json"):
            rc = lessons.cmd_seed(type("A", (), {"root": self.root})())
        self.assertEqual(rc, 1)


def _mkargs(root, **kw):
    """构造一个命名空间对象，缺省字段按常用默认值补齐。"""
    class A:
        pass
    a = A()
    a.root = root
    defaults = dict(scene=None, solution=None, problem=None, tags=None,
                    kind="结论", source="", from_bug=None, use_global=False,
                    query="", top=5, file=None, days=180, id=None)
    for k, v in defaults.items():
        setattr(a, k, v)
    for k, v in kw.items():
        setattr(a, k, v)
    return a


class _StoreTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.store = os.path.join(self.root, ".lunyu", "lessons.json")

    def args(self, **kw):
        return _mkargs(self.root, **kw)

    def data(self):
        with open(self.store, encoding="utf-8") as f:
            return json.load(f)

    def seed(self, items):
        """直接写入经验库（可造出老数据）。"""
        os.makedirs(os.path.join(self.root, ".lunyu"), exist_ok=True)
        lessons.save(self.store, {"next_id": len(items) + 1, "lessons": items})


class FromBugTest(_StoreTest):
    """缺陷 -> 经验一键转化（复盘不再手动重录）。"""

    @property
    def bugs_path(self):
        return os.path.join(self.root, ".lunyu", "bugs.json")

    def write_bugs(self, bugs):
        os.makedirs(os.path.join(self.root, ".lunyu"), exist_ok=True)
        with open(self.bugs_path, "w", encoding="utf-8") as f:
            json.dump({"next_id": len(bugs) + 1, "bugs": bugs}, f, ensure_ascii=False)

    def closed_bug(self, **kw):
        bug = {"id": "BUG-0001", "title": "按钮不响应", "priority": "P1",
               "status": "关闭", "root_cause": "编码疏漏",
               "regression": "tests/test_btn.py::test_click", "related_pr": ""}
        bug.update(kw)
        return bug

    def test_from_bug_builds_lesson(self):
        self.write_bugs([self.closed_bug()])
        rc = lessons.cmd_add(self.args(from_bug="BUG-0001"))
        self.assertEqual(rc, 0)
        it = self.data()["lessons"][0]
        self.assertEqual(it["scene"], "按钮不响应")
        self.assertEqual(it["problem"], "编码疏漏")
        self.assertEqual(it["solution"], "tests/test_btn.py::test_click")
        self.assertEqual(it["kind"], "踩坑")
        self.assertEqual(it["source"], "BUG-0001")
        self.assertIn("缺陷", it["tags"])
        self.assertIn("P1", it["tags"])

    def test_from_bug_short_id(self):
        """--from-bug 1 / 0001 也应能定位到 BUG-0001。"""
        self.write_bugs([self.closed_bug()])
        self.assertEqual(lessons.cmd_add(self.args(from_bug="1")), 0)
        self.assertEqual(self.data()["lessons"][0]["source"], "BUG-0001")

    def test_from_bug_falls_back_to_pr(self):
        """没有回归用例时退回关联 PR，仍要留痕。"""
        self.write_bugs([self.closed_bug(regression="", related_pr="PR-88")])
        lessons.cmd_add(self.args(from_bug="BUG-0001"))
        self.assertEqual(self.data()["lessons"][0]["solution"], "PR-88")

    def test_from_bug_unclosed_returns_1(self):
        self.write_bugs([self.closed_bug(status="修复中")])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = lessons.cmd_add(self.args(from_bug="BUG-0001"))
        self.assertEqual(rc, 1)
        self.assertIn("尚未关闭", buf.getvalue())
        self.assertFalse(os.path.exists(self.store))

    def test_from_bug_missing_returns_1(self):
        self.write_bugs([self.closed_bug()])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = lessons.cmd_add(self.args(from_bug="BUG-9999"))
        self.assertEqual(rc, 1)
        self.assertIn("没有 BUG-9999", buf.getvalue())

    def test_from_bug_no_ledger_returns_1(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = lessons.cmd_add(self.args(from_bug="BUG-0001"))
        self.assertEqual(rc, 1)
        self.assertIn("未找到缺陷台账", buf.getvalue())

    def test_from_bug_bad_json_returns_1(self):
        os.makedirs(os.path.join(self.root, ".lunyu"), exist_ok=True)
        with open(self.bugs_path, "w", encoding="utf-8") as f:
            f.write("{ 坏 json")
        with redirect_stdout(io.StringIO()):
            rc = lessons.cmd_add(self.args(from_bug="BUG-0001"))
        self.assertEqual(rc, 1)

    def test_add_without_scene_returns_1(self):
        with redirect_stdout(io.StringIO()):
            rc = lessons.cmd_add(self.args(scene="", solution="x"))
        self.assertEqual(rc, 1)


class ImportTest(_StoreTest):
    """export 出去的 markdown 必须能 import 回来（不能是单向死产物）。"""

    def md(self, rows):
        p = os.path.join(self.root, "in.md")
        lines = ["# 经验库导出", "",
                 "| 编号 | 类型 | 场景 | 踩坑 | 结论 | 标签 | 命中 | 日期 |",
                 "|---|---|---|---|---|---|---|---|"]
        lines += rows
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return p

    def test_roundtrip_is_idempotent(self):
        """导出再导回，条数不变（幂等）。"""
        lessons.cmd_add(self.args(scene="车机广播", solution="动态注册", problem="manifest 被忽略",
                                  tags="车机,广播", kind="踩坑"))
        out = os.path.join(self.root, "out.md")
        lessons.cmd_export(_mkargs(self.root, out=out))
        rc = lessons.cmd_import(self.args(file=out))
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.data()["lessons"]), 1)
        # 再导一次仍然只有一条
        lessons.cmd_import(self.args(file=out))
        self.assertEqual(len(self.data()["lessons"]), 1)

    def test_import_adds_new_ids(self):
        p = self.md(["| L-0007 | 踩坑 | 场景七 | 坑 | 解法 | #a #缺陷 | 2 | 2026-01-01 |"])
        rc = lessons.cmd_import(self.args(file=p))
        self.assertEqual(rc, 0)
        d = self.data()
        self.assertEqual(d["lessons"][0]["id"], "L-0007")
        self.assertEqual(d["lessons"][0]["tags"], ["a", "缺陷"])
        self.assertEqual(d["lessons"][0]["hits"], 2)
        self.assertGreater(d["next_id"], 7)  # 不能和导入的编号撞车

    def test_import_conflict_keeps_newer(self):
        self.seed([{"id": "L-0001", "kind": "结论", "scene": "旧场景", "problem": "",
                    "solution": "旧结论", "tags": [], "hits": 5,
                    "created_at": "2020-01-01 00:00:00", "date": "2020-01-01"}])
        p = self.md(["| L-0001 | 结论 | 新场景 | | 新结论 | #x | 2 | 2026-05-05 |"])
        lessons.cmd_import(self.args(file=p))
        it = self.data()["lessons"][0]
        self.assertEqual(it["solution"], "新结论")
        self.assertEqual(it["hits"], 5)  # 命中次数取大者，不丢热度
        self.assertEqual(len(self.data()["lessons"]), 1)

    def test_import_conflict_keeps_local_when_local_newer(self):
        self.seed([{"id": "L-0001", "kind": "结论", "scene": "本地场景", "problem": "",
                    "solution": "本地结论", "tags": [], "hits": 1,
                    "created_at": "2026-10-01 00:00:00", "date": "2026-10-01"}])
        p = self.md(["| L-0001 | 结论 | 外部场景 | | 外部结论 | #x | 2 | 2020-01-01 |"])
        lessons.cmd_import(self.args(file=p))
        self.assertEqual(self.data()["lessons"][0]["solution"], "本地结论")

    def test_import_missing_file_returns_1(self):
        with redirect_stdout(io.StringIO()):
            rc = lessons.cmd_import(self.args(file=os.path.join(self.root, "nope.md")))
        self.assertEqual(rc, 1)

    def test_import_garbage_returns_1(self):
        p = os.path.join(self.root, "garbage.md")
        with open(p, "w", encoding="utf-8") as f:
            f.write("随便写点什么\n不是表格\n")
        with redirect_stdout(io.StringIO()):
            rc = lessons.cmd_import(self.args(file=p))
        self.assertEqual(rc, 1)

    def test_parse_skips_header_and_dirty_rows(self):
        p = self.md(["| L-0002 | 结论 | 场景 | | 结论 | #t | 1 | 2026-01-01 |",
                     "| 缺列的行 |", "随便一行"])
        items, err = lessons.parse_markdown(p)
        self.assertIsNone(err)
        self.assertEqual([it["id"] for it in items], ["L-0002"])


class GlobalTest(_StoreTest):
    """全局库：换项目也能沉淀组织级经验。"""

    def setUp(self):
        super().setUp()
        self.gtmp = tempfile.mkdtemp()
        self.gpath = os.path.join(self.gtmp, "lessons.json")

    def gargs(self, **kw):
        return _mkargs(self.root, use_global=True, **kw)

    def test_add_global_writes_global_store(self):
        with patch.object(lessons, "global_store_path", return_value=self.gpath):
            rc = lessons.cmd_add(self.gargs(scene="组织级经验", solution="统一做法",
                                            problem="", tags="通用", kind="结论"))
        self.assertEqual(rc, 0)
        with open(self.gpath, encoding="utf-8") as f:
            d = json.load(f)
        self.assertEqual(len(d["lessons"]), 1)
        self.assertFalse(os.path.exists(self.store))  # 没污染本地库

    def test_search_merges_local_and_global(self):
        lessons.cmd_add(self.args(scene="车机广播", solution="动态注册", problem="",
                                  tags="车机", kind="结论"))
        with patch.object(lessons, "global_store_path", return_value=self.gpath):
            lessons.cmd_add(self.gargs(scene="车机音频", solution="延迟初始化", problem="",
                                       tags="车机", kind="结论"))
            buf = io.StringIO()
            with redirect_stdout(buf):
                lessons.cmd_search(self.args(query="车机", top=5))
        out = buf.getvalue()
        self.assertIn("（本地）", out)
        self.assertIn("（全局）", out)
        self.assertLess(out.index("（本地）"), out.index("（全局）"))  # 本地优先展示

    def test_search_hits_written_back_to_each_store(self):
        lessons.cmd_add(self.args(scene="车机广播", solution="动态注册", problem="",
                                  tags="车机", kind="结论"))
        with patch.object(lessons, "global_store_path", return_value=self.gpath):
            lessons.cmd_add(self.gargs(scene="车机音频", solution="延迟初始化", problem="",
                                       tags="车机", kind="结论"))
            with redirect_stdout(io.StringIO()):
                lessons.cmd_search(self.args(query="车机", top=5))
        self.assertEqual(self.data()["lessons"][0]["hits"], 1)
        with open(self.gpath, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["lessons"][0]["hits"], 1)

    def test_search_global_only(self):
        lessons.cmd_add(self.args(scene="车机广播", solution="本地结论", problem="",
                                  tags="车机", kind="结论"))
        with patch.object(lessons, "global_store_path", return_value=self.gpath):
            lessons.cmd_add(self.gargs(scene="车机音频", solution="全局结论", problem="",
                                       tags="车机", kind="结论"))
            buf = io.StringIO()
            with redirect_stdout(buf):
                lessons.cmd_search(self.gargs(query="车机", top=5))
        self.assertIn("全局结论", buf.getvalue())
        self.assertNotIn("本地结论", buf.getvalue())


class StaleReviewTest(_StoreTest):
    """过期复核：技术会变，老结论要重验。"""

    def old(self, days, **kw):
        d = datetime.now() - timedelta(days=days)
        item = {"id": "L-0001", "kind": "结论", "scene": "车机广播", "problem": "",
                "solution": "动态注册兜底", "tags": ["车机"], "hits": 0,
                "created_at": d.strftime("%Y-%m-%d %H:%M:%S"),
                "date": d.strftime("%Y-%m-%d")}
        item.update(kw)
        return item

    def test_old_lesson_is_stale(self):
        self.seed([self.old(200)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = lessons.cmd_stale(self.args(days=180))
        self.assertEqual(rc, 0)
        self.assertIn("L-0001", buf.getvalue())

    def test_fresh_lesson_not_stale(self):
        self.seed([self.old(10)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            lessons.cmd_stale(self.args(days=180))
        self.assertNotIn("L-0001", buf.getvalue())

    def test_custom_days(self):
        self.seed([self.old(30)])
        buf = io.StringIO()
        with redirect_stdout(buf):
            lessons.cmd_stale(self.args(days=7))
        self.assertIn("L-0001", buf.getvalue())

    def test_review_marks_reviewed_at(self):
        self.seed([self.old(200)])
        rc = lessons.cmd_review(self.args(id="L-0001"))
        self.assertEqual(rc, 0)
        self.assertIn("reviewed_at", self.data()["lessons"][0])

    def test_reviewed_lesson_drops_out_of_stale(self):
        self.seed([self.old(200)])
        lessons.cmd_review(self.args(id="L-0001"))
        buf = io.StringIO()
        with redirect_stdout(buf):
            lessons.cmd_stale(self.args(days=180))
        self.assertNotIn("L-0001", buf.getvalue())

    def test_review_missing_id_returns_1(self):
        self.seed([self.old(200)])
        with redirect_stdout(io.StringIO()):
            rc = lessons.cmd_review(self.args(id="L-9999"))
        self.assertEqual(rc, 1)

    def test_missing_date_is_not_stale(self):
        """脏数据（无日期）不能误报成过期。"""
        self.seed([{"id": "L-0002", "kind": "结论", "scene": "s", "solution": "x", "tags": []}])
        buf = io.StringIO()
        with redirect_stdout(buf):
            lessons.cmd_stale(self.args(days=1))
        self.assertNotIn("L-0002", buf.getvalue())


class ToleranceTest(unittest.TestCase):
    """坏 JSON / 结构异常都不能崩。"""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.store = os.path.join(self.root, ".lunyu", "lessons.json")
        os.makedirs(os.path.dirname(self.store))

    def test_load_missing_file(self):
        self.assertEqual(lessons.load(os.path.join(self.root, "nope.json")),
                         {"next_id": 1, "lessons": []})

    def test_load_bad_json(self):
        with open(self.store, "w", encoding="utf-8") as f:
            f.write("{ 坏 json")
        self.assertEqual(lessons.load(self.store), {"next_id": 1, "lessons": []})

    def test_search_on_bad_json_does_not_crash(self):
        with open(self.store, "w", encoding="utf-8") as f:
            f.write("[]")
        with patch.object(lessons, "global_store_path",
                          return_value=os.path.join(self.root, "g.json")):
            with redirect_stdout(io.StringIO()):
                rc = lessons.cmd_search(_mkargs(self.root, query="车机"))
        self.assertEqual(rc, 0)
