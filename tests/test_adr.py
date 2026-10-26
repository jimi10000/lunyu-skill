#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adr.py 单元测试

用临时目录模拟 .lunyu/decisions/ + decisions.json，验证:
- new 递增编号与正文落盘
- list / show
- supersede 状态流转（旧留痕可追溯）
- link 关联版本
- 编号不存在时退出码 1
- 索引损坏时自动重建
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import adr


class AdrTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, ".git"), exist_ok=True)  # 让 find_root 找到
        self.path = os.path.join(self.tmp, ".lunyu", "decisions.json")
        self.ddir = os.path.join(self.tmp, ".lunyu", "decisions")

    def make_args(self, **kw):
        class A:
            pass

        a = A()
        defaults = {
            "root": self.tmp,
            "title": "默认决策",
            "context": "默认背景",
            "decision": "默认决定",
            "alternatives": [],
            "consequences": "默认影响",
            "positive": "",
            "negative": "",
            "status": "已接受",
            "related_version": "",
            "id": None,
            "by": None,
            "version": None,
        }
        for k, v in defaults.items():
            setattr(a, k, v)
        for k, v in kw.items():
            setattr(a, k, v)
        return a

    def new_adr(self, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            adr.cmd_new(self.make_args(**kw))
        return buf.getvalue()

    # ---------------- new ----------------
    def test_new_writes_md_and_index(self):
        self.new_adr(title="统一用 SQLite 还是 JSON 落盘",
                     context="技能要记台账但要求零依赖",
                     decision="选 JSON 文件落盘",
                     alternatives=["SQLite|引入外部依赖且不便 diff", "YAML:解析需第三方库"],
                     consequences="够用且易读，但并发写要自己兜",
                     positive="零依赖、可直接 git diff",
                     negative="大文件检索需全量加载",
                     related_version="v1.0.0")
        data = adr.load(self.path)
        self.assertEqual(len(data["decisions"]), 1)
        self.assertEqual(data["next_id"], 2)
        it = data["decisions"][0]
        self.assertEqual(it["id"], "0001")
        self.assertEqual(it["status"], "已接受")
        self.assertEqual(it["related_versions"], ["v1.0.0"])
        self.assertEqual(len(it["alternatives"]), 2)
        self.assertEqual(it["alternatives"][0]["name"], "SQLite")
        self.assertEqual(it["alternatives"][0]["reason"], "引入外部依赖且不便 diff")

        md_path = os.path.join(self.ddir, it["file"])
        self.assertTrue(os.path.exists(md_path))
        with open(md_path, encoding="utf-8") as f:
            body = f.read()
        self.assertIn("# 0001 统一用 SQLite 还是 JSON 落盘", body)
        self.assertIn("- 状态：已接受", body)
        self.assertIn("## 背景", body)
        self.assertIn("## 决定", body)
        self.assertIn("## 备选方案（及否决理由）", body)
        self.assertIn("否决理由：引入外部依赖且不便 diff", body)
        self.assertIn("- 正面：零依赖、可直接 git diff", body)
        self.assertIn("- 负面：大文件检索需全量加载", body)
        self.assertIn("## 关联版本", body)

    def test_id_increments(self):
        self.new_adr(title="第一条", context="c", decision="d", consequences="e")
        self.new_adr(title="第二条", context="c", decision="d", consequences="e")
        data = adr.load(self.path)
        self.assertEqual([it["id"] for it in data["decisions"]], ["0001", "0002"])
        self.assertEqual(data["next_id"], 3)
        self.assertTrue(os.path.exists(os.path.join(self.ddir, "0001-第一条.md")))
        self.assertTrue(os.path.exists(os.path.join(self.ddir, "0002-第二条.md")))

    def test_slug_keeps_chinese(self):
        self.assertEqual(adr.slugify("统一用 SQLite 还是 JSON 落盘"), "统一用-sqlite-还是-json-落盘")
        self.assertEqual(adr.slugify("Use Redis!!"), "use-redis")
        self.assertEqual(adr.slugify("###"), "adr")

    def test_pending_status(self):
        self.new_adr(title="待定项", context="c", decision="d", consequences="e", status="待定")
        data = adr.load(self.path)
        self.assertEqual(data["decisions"][0]["status"], "待定")

    # ---------------- list / show ----------------
    def test_list(self):
        self.new_adr(title="第一条", context="c", decision="d", consequences="e")
        self.new_adr(title="第二条", context="c", decision="d", consequences="e", status="已弃用")
        buf = io.StringIO()
        with redirect_stdout(buf):
            adr.cmd_list(self.make_args(status=None))
        out = buf.getvalue()
        self.assertIn("0001", out)
        self.assertIn("0002", out)
        self.assertIn("已弃用", out)
        self.assertIn("共 2 条", out)

        buf = io.StringIO()
        with redirect_stdout(buf):
            adr.cmd_list(self.make_args(status="已弃用"))
        self.assertNotIn("0001", buf.getvalue())
        self.assertIn("0002", buf.getvalue())

    def test_list_empty(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            adr.cmd_list(self.make_args(status=None))
        self.assertIn("暂无架构决策记录", buf.getvalue())

    def test_show(self):
        self.new_adr(title="选 JSON 落盘", context="c", decision="d", consequences="e")
        buf = io.StringIO()
        with redirect_stdout(buf):
            adr.cmd_show(self.make_args(id="1"))
        out = buf.getvalue()
        self.assertIn("# 0001 选 JSON 落盘", out)
        self.assertIn("## 决定", out)

    def test_show_missing_exit1(self):
        with self.assertRaises(SystemExit) as ctx:
            adr.cmd_show(self.make_args(id="0009"))
        self.assertEqual(ctx.exception.code, 1)

    # ---------------- supersede ----------------
    def test_supersede_updates_both_sides(self):
        self.new_adr(title="先用 JSON", context="c", decision="d", consequences="e")
        self.new_adr(title="改用 SQLite", context="c", decision="d", consequences="e")
        adr.cmd_supersede(self.make_args(id="0001", by="0002"))
        data = adr.load(self.path)
        old, new = data["decisions"][0], data["decisions"][1]
        self.assertEqual(old["status"], "已被取代")
        self.assertEqual(old["superseded_by"], "0002")
        self.assertIn("0001", new["supersedes"])

        with open(os.path.join(self.ddir, old["file"]), encoding="utf-8") as f:
            old_body = f.read()
        self.assertIn("- 状态：已被取代", old_body)
        self.assertIn("- 已被取代：ADR 0002", old_body)
        with open(os.path.join(self.ddir, new["file"]), encoding="utf-8") as f:
            new_body = f.read()
        self.assertIn("- 取代了：ADR 0001", new_body)

    def test_supersede_missing_old_exit1(self):
        self.new_adr(title="a", context="c", decision="d", consequences="e")
        with self.assertRaises(SystemExit) as ctx:
            adr.cmd_supersede(self.make_args(id="0009", by="0001"))
        self.assertEqual(ctx.exception.code, 1)

    def test_supersede_missing_new_exit1(self):
        self.new_adr(title="a", context="c", decision="d", consequences="e")
        with self.assertRaises(SystemExit) as ctx:
            adr.cmd_supersede(self.make_args(id="0001", by="0009"))
        self.assertEqual(ctx.exception.code, 1)

    # ---------------- link ----------------
    def test_link_version(self):
        self.new_adr(title="选 JSON 落盘", context="c", decision="d", consequences="e")
        buf = io.StringIO()
        with redirect_stdout(buf):
            adr.cmd_link(self.make_args(id="0001", version="v1.2.0"))
        self.assertIn("v1.2.0", buf.getvalue())
        data = adr.load(self.path)
        self.assertEqual(data["decisions"][0]["related_versions"], ["v1.2.0"])
        # 重复关联不产生重复项
        with redirect_stdout(io.StringIO()):
            adr.cmd_link(self.make_args(id="0001", version="v1.2.0"))
        data = adr.load(self.path)
        self.assertEqual(data["decisions"][0]["related_versions"], ["v1.2.0"])
        with open(os.path.join(self.ddir, data["decisions"][0]["file"]), encoding="utf-8") as f:
            self.assertIn("- 关联版本：v1.2.0", f.read())

    def test_link_missing_exit1(self):
        with self.assertRaises(SystemExit) as ctx:
            adr.cmd_link(self.make_args(id="0009", version="v1.0.0"))
        self.assertEqual(ctx.exception.code, 1)

    # ---------------- 容错 ----------------
    def test_corrupt_index_rebuilds(self):
        self.new_adr(title="第一条", context="c", decision="d", consequences="e")
        self.new_adr(title="第二条", context="c", decision="d", consequences="e", status="已弃用")
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ 这不是合法 JSON")
        buf = io.StringIO()
        with redirect_stdout(buf):
            data = adr.load(self.path)
        self.assertIn("重建", buf.getvalue())
        self.assertEqual(len(data["decisions"]), 2)
        self.assertEqual(data["next_id"], 3)
        self.assertEqual(data["decisions"][0]["id"], "0001")
        self.assertEqual(data["decisions"][1]["status"], "已弃用")

    def test_corrupt_index_not_dict_rebuilds(self):
        adr.store_path(self.tmp)  # 先让 .lunyu/ 存在
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        with redirect_stdout(io.StringIO()):
            data = adr.load(self.path)
        self.assertEqual(data, {"next_id": 1, "decisions": []})

    def test_missing_dir_is_created(self):
        self.assertFalse(os.path.exists(self.path))
        self.new_adr(title="a", context="c", decision="d", consequences="e")
        self.assertTrue(os.path.isdir(self.ddir))
        self.assertTrue(os.path.exists(self.path))

    # ---------------- CLI ----------------
    def test_cli_new_show_list(self):
        with redirect_stdout(io.StringIO()):
            rc = adr.main(["new", "--root", self.tmp, "--title", "选 JSON 落盘",
                           "--context", "零依赖要求", "--decision", "用 JSON",
                           "--alternatives", "SQLite|有依赖", "--consequences", "够用",
                           "--related-version", "v1.0.0"])
        self.assertEqual(rc, 0)
        buf = io.StringIO()
        with redirect_stdout(buf):
            adr.main(["show", "0001", "--root", self.tmp])
        self.assertIn("选 JSON 落盘", buf.getvalue())
        buf = io.StringIO()
        with redirect_stdout(buf):
            adr.main(["list", "--root", self.tmp])
        self.assertIn("0001", buf.getvalue())

    def test_cli_supersede_and_link(self):
        with redirect_stdout(io.StringIO()):
            adr.main(["new", "--root", self.tmp, "--title", "A", "--context", "c",
                      "--decision", "d", "--consequences", "e"])
            adr.main(["new", "--root", self.tmp, "--title", "B", "--context", "c",
                      "--decision", "d", "--consequences", "e"])
            rc_super = adr.main(["supersede", "0001", "--by", "0002", "--root", self.tmp])
            rc_link = adr.main(["link", "--id", "0002", "--version", "v2.0.0",
                                "--root", self.tmp])
        self.assertEqual(rc_super, 0)
        self.assertEqual(rc_link, 0)
        data = adr.load(self.path)
        self.assertEqual(data["decisions"][0]["status"], "已被取代")
        self.assertEqual(data["decisions"][1]["related_versions"], ["v2.0.0"])


if __name__ == "__main__":
    unittest.main()
