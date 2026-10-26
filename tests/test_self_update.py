# -*- coding: utf-8 -*-
"""self_update.py 单元测试。

重点覆盖：
  - parse_version：顶层 version 优先、metadata 子层回退（这是之前 .sh 版本的坑）
  - vtuple / is_newer：语义化版本比较，v 前缀兼容
  - find_skill_root：Release 附件与分支归档两种 zip 结构
  - apply_update：覆盖写入 + 保留 .lunyu 数据 + 清理旧文件
"""

import importlib.util
import io
import itertools
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import self_update  # noqa: E402

REAL_SELF_UPDATE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "self_update.py"
)
_mod_seq = itertools.count()


def load_self_update_at(skill_dir):
    """在临时技能目录里加载一份真实的 self_update.py。

    __file__ 天然指向 <skill_dir>/scripts/，因此不需要 patch 被测模块本身：
    本地版本读取、远端 SKILL.md 解析、is_newer 版本比较全都是真实执行。
    """
    dst = os.path.join(skill_dir, "scripts", "self_update.py")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(REAL_SELF_UPDATE, dst)
    spec = importlib.util.spec_from_file_location(
        "self_update_under_test_%d" % next(_mod_seq), dst
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write(path, content):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def seed_manifest(skill_dir, files):
    """模拟"上次安装"落盘的清单。"""
    write(
        os.path.join(skill_dir, self_update.MANIFEST_NAME),
        '{"version": 1, "files": [%s]}' % ", ".join('"%s"' % f for f in files),
    )


class ParseVersionTest(unittest.TestCase):
    def test_top_level_version_preferred(self):
        """顶层 version 优先被读到（技能市场解析器也只读顶层）。"""
        text = (
            '---\nname: lunyu\nversion: "1.1.4"\n'
            "metadata:\n  version: \"0.0.1\"\n---\n\n# body\n"
        )
        self.assertEqual(self_update.parse_version(text), "1.1.4")

    def test_fallback_to_indented_metadata(self):
        """顶层没有时回退到 metadata 子层（兼容旧包）。"""
        text = "---\nname: lunyu\nmetadata:\n  category: x\n  version: \"1.0.9\"\n---\n"
        self.assertEqual(self_update.parse_version(text), "1.0.9")

    def test_empty_when_no_version(self):
        self.assertEqual(self_update.parse_version("---\nname: lunyu\n---\n"), "")

    def test_does_not_read_body_version(self):
        """正文里的 version 字样不应被误读（除非 frontmatter 里确实没有）。"""
        text = '---\nname: lunyu\nversion: "2.0.0"\n---\n\n正文提到 version: 9.9.9\n'
        self.assertEqual(self_update.parse_version(text), "2.0.0")


class VersionCompareTest(unittest.TestCase):
    def test_vtuple_basic(self):
        self.assertEqual(self_update.vtuple("1.2.3"), (1, 2, 3, 0))
        self.assertEqual(self_update.vtuple("v1.2.3"), (1, 2, 3, 0))

    def test_vtuple_pads_short(self):
        self.assertEqual(self_update.vtuple("2.0"), (2, 0, 0, 0))

    def test_newer_than(self):
        self.assertTrue(self_update.is_newer("1.1.4", "1.1.3"))
        self.assertTrue(self_update.is_newer("2.0.0", "1.9.9"))

    def test_not_newer_when_equal(self):
        self.assertFalse(self_update.is_newer("1.1.4", "1.1.4"))

    def test_not_newer_when_older(self):
        """远端更旧时不能降级。"""
        self.assertFalse(self_update.is_newer("1.1.2", "1.1.4"))

    def test_v_prefix_tolerated(self):
        self.assertTrue(self_update.is_newer("v1.1.4", "1.1.3"))


class FindSkillRootTest(unittest.TestCase):
    def test_release_zip_layout(self):
        """Release 附件结构：lunyu/SKILL.md"""
        tmp = tempfile.mkdtemp()
        write(os.path.join(tmp, "lunyu", "SKILL.md"), "---\nversion: '1.0'\n---\n")
        self.assertTrue(self_update.find_skill_root(tmp).endswith("lunyu"))

    def test_archive_zip_layout(self):
        """分支归档结构：lunyu-skill-main/SKILL.md"""
        tmp = tempfile.mkdtemp()
        write(os.path.join(tmp, "lunyu-skill-main", "SKILL.md"), "---\nversion: '1.0'\n---\n")
        self.assertTrue(self_update.find_skill_root(tmp).endswith("lunyu-skill-main"))

    def test_none_when_missing(self):
        tmp = tempfile.mkdtemp()
        write(os.path.join(tmp, "README.md"), "x")
        self.assertIsNone(self_update.find_skill_root(tmp))


class ApplyUpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.skill = os.path.join(self.tmp, "skill")
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.skill)
        os.makedirs(self.src)

    def _new_pkg(self):
        write(os.path.join(self.src, "SKILL.md"), '---\nversion: "1.1.4"\n---\n')
        write(os.path.join(self.src, "scripts", "self_update.py"), "print('new')")

    def test_overwrites_files(self):
        write(os.path.join(self.skill, "SKILL.md"), '---\nversion: "1.0.0"\n---\n')
        write(os.path.join(self.src, "SKILL.md"), '---\nversion: "1.1.4"\n---\n')
        write(os.path.join(self.src, "scripts", "flow.py"), "print('new')")
        w, _ = self_update.apply_update(self.skill, self.src)
        self.assertGreaterEqual(w, 2)
        with open(os.path.join(self.skill, "SKILL.md"), encoding="utf-8") as f:
            self.assertIn("1.1.4", f.read())

    def test_preserves_lunyu_data(self):
        """.lunyu 用户数据必须原样保留（缺陷台账/报告都在这里）。"""
        write(os.path.join(self.skill, ".lunyu", "bugs.json"), '{"bugs":[]}')
        write(os.path.join(self.skill, "SKILL.md"), '---\nversion: "1.0.0"\n---\n')
        write(os.path.join(self.src, "SKILL.md"), '---\nversion: "1.1.4"\n---\n')
        self_update.apply_update(self.skill, self.src)
        with open(os.path.join(self.skill, ".lunyu", "bugs.json"), encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"bugs":[]}')

    def test_prunes_removed_files(self):
        """清单内有、远端包里没有的文件应被清理。"""
        write(os.path.join(self.skill, "scripts", "old_tool.py"), "x")
        seed_manifest(self.skill, ["SKILL.md", "scripts/old_tool.py"])
        self._new_pkg()
        _, removed = self_update.apply_update(self.skill, self.src, prune=True)
        self.assertIn("scripts/old_tool.py", removed)
        self.assertFalse(os.path.exists(os.path.join(self.skill, "scripts", "old_tool.py")))

    def test_no_prune_keeps_files(self):
        write(os.path.join(self.skill, "scripts", "old_tool.py"), "x")
        seed_manifest(self.skill, ["SKILL.md", "scripts/old_tool.py"])
        self._new_pkg()
        self_update.apply_update(self.skill, self.src, prune=False)
        self.assertTrue(os.path.exists(os.path.join(self.skill, "scripts", "old_tool.py")))


class DataSafetyTest(unittest.TestCase):
    """修复核心：任何时刻磁盘上都有一份完整的 .lunyu/，失败自动回滚。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.skill = os.path.join(self.tmp, "skill")
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.skill)
        os.makedirs(self.src)
        self.data = os.path.join(self.skill, ".lunyu")
        self.old_tmp = os.path.join(self.skill, ".lunyu.old.tmp")
        write(os.path.join(self.data, "bugs.json"), '{"bugs":[{"id":1}]}')
        write(os.path.join(self.data, "reports", "daily.md"), "# 日报")
        write(os.path.join(self.skill, "SKILL.md"), '---\nversion: "1.0.0"\n---\n')
        seed_manifest(self.skill, ["SKILL.md"])
        write(os.path.join(self.src, "SKILL.md"), '---\nversion: "1.1.4"\n---\n')
        write(os.path.join(self.src, "scripts", "flow.py"), "print('new')")

    def _assert_data_intact(self):
        self.assertTrue(os.path.isdir(self.data), ".lunyu 必须还在原位")
        self.assertEqual(read(os.path.join(self.data, "bugs.json")), '{"bugs":[{"id":1}]}')
        self.assertEqual(read(os.path.join(self.data, "reports", "daily.md")), "# 日报")

    def test_rollback_when_restore_fails(self):
        """恢复阶段抛异常 -> 旧目录被换回，数据完好。"""
        with patch.object(self_update, "restore_data",
                          side_effect=RuntimeError("模拟恢复失败")):
            with self.assertRaises(RuntimeError):
                self_update.apply_update(self.skill, self.src)
        self._assert_data_intact()
        self.assertFalse(os.path.exists(self.old_tmp), "回滚后不能留 .lunyu.old.tmp")

    def test_rollback_when_write_fails(self):
        """覆盖写入中途失败（模拟磁盘满）-> 数据完好。"""
        real_copy = shutil.copy2

        def boom(s, d, *a, **k):
            if os.path.basename(s) == "flow.py":
                raise OSError("No space left on device")
            return real_copy(s, d, *a, **k)

        with patch.object(shutil, "copy2", side_effect=boom):
            with self.assertRaises(OSError):
                self_update.apply_update(self.skill, self.src)
        self._assert_data_intact()
        self.assertFalse(os.path.exists(self.old_tmp))

    def test_rollback_on_keyboard_interrupt(self):
        """Ctrl-C 也走同一条回滚路径（BaseException，不能被吞）。"""
        with patch.object(self_update, "restore_data",
                          side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                self_update.apply_update(self.skill, self.src)
        self._assert_data_intact()

    def test_old_tmp_cleaned_on_success(self):
        written, _ = self_update.apply_update(self.skill, self.src)
        self.assertGreaterEqual(written, 2)
        self._assert_data_intact()
        self.assertFalse(os.path.exists(self.old_tmp), "成功路径必须清理 .lunyu.old.tmp")
        self.assertFalse(os.path.exists(os.path.join(self.skill, ".lunyu.bak.tmp")))

    def test_legacy_bak_tmp_is_cleaned(self):
        """老版本失败留下的 .lunyu.bak.tmp 不能永久残留。"""
        write(os.path.join(self.skill, ".lunyu.bak.tmp", "bugs.json"), "旧备份")
        self_update.apply_update(self.skill, self.src)
        self.assertFalse(os.path.exists(os.path.join(self.skill, ".lunyu.bak.tmp")))
        self._assert_data_intact()

    def test_recovers_data_from_interrupted_previous_run(self):
        """上次更新被中断（数据在 .lunyu.old.tmp，原位没有）-> 本次先救回。"""
        os.replace(self.data, self.old_tmp)
        self.assertFalse(os.path.isdir(self.data))
        self_update.apply_update(self.skill, self.src)
        self._assert_data_intact()
        self.assertFalse(os.path.exists(self.old_tmp))

    def test_no_data_dir_is_fine(self):
        """全新安装（本来就没有 .lunyu）不应报错，也不应造出空目录。"""
        shutil.rmtree(self.data)
        written, _ = self_update.apply_update(self.skill, self.src)
        self.assertGreaterEqual(written, 2)
        self.assertFalse(os.path.exists(self.old_tmp))


class ManifestPruneTest(unittest.TestCase):
    """prune 只能按清单删，不再靠路径前缀猜。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.skill = os.path.join(self.tmp, "skill")
        self.src = os.path.join(self.tmp, "src")
        os.makedirs(self.skill)
        os.makedirs(self.src)
        write(os.path.join(self.skill, "SKILL.md"), '---\nversion: "1.0.0"\n---\n')
        write(os.path.join(self.src, "SKILL.md"), '---\nversion: "1.1.4"\n---\n')

    def test_no_manifest_prunes_nothing(self):
        """无清单（老版本升级）-> 一个文件都不删。"""
        write(os.path.join(self.skill, "scripts", "old_tool.py"), "x")
        write(os.path.join(self.skill, "docs", "obsolete.md"), "x")
        write(os.path.join(self.skill, "legacy_root.md"), "x")
        _, removed = self_update.apply_update(self.skill, self.src, prune=True)
        self.assertEqual(removed, [])
        for rel in ("scripts/old_tool.py", "docs/obsolete.md", "legacy_root.md"):
            self.assertTrue(os.path.exists(os.path.join(self.skill, *rel.split("/"))), rel)

    def test_corrupt_manifest_prunes_nothing(self):
        write(os.path.join(self.skill, "scripts", "old_tool.py"), "x")
        write(os.path.join(self.skill, self_update.MANIFEST_NAME), "{ 这不是 JSON")
        _, removed = self_update.apply_update(self.skill, self.src, prune=True)
        self.assertEqual(removed, [])
        self.assertTrue(os.path.exists(os.path.join(self.skill, "scripts", "old_tool.py")))

    def test_user_files_never_pruned(self):
        """不在清单里的用户自建文件必须活着。"""
        write(os.path.join(self.skill, "scripts", "old_tool.py"), "x")  # 清单内
        seed_manifest(self.skill, ["SKILL.md", "scripts/old_tool.py"])
        write(os.path.join(self.skill, "我的笔记.md"), "别删我")
        write(os.path.join(self.skill, "docs", "私有方案.md"), "别删我")
        write(os.path.join(self.skill, "tests", "my_local_test.py"), "别删我")
        write(os.path.join(self.skill, "scripts", "my_helper.py"), "别删我")
        _, removed = self_update.apply_update(self.skill, self.src, prune=True)
        self.assertEqual(removed, ["scripts/old_tool.py"])
        for rel in ("我的笔记.md", "docs/私有方案.md", "tests/my_local_test.py",
                    "scripts/my_helper.py"):
            self.assertTrue(os.path.exists(os.path.join(self.skill, *rel.split("/"))), rel)

    def test_manifest_written_after_update(self):
        """每次安装都落盘清单，作为下一次 prune 的唯一依据。"""
        write(os.path.join(self.src, "scripts", "a.py"), "a")
        write(os.path.join(self.src, "docs", "b.md"), "b")
        self_update.apply_update(self.skill, self.src)
        m = self_update.read_manifest(self.skill)
        self.assertIsNotNone(m)
        self.assertIn("scripts/a.py", m)
        self.assertIn("docs/b.md", m)
        self.assertIn("SKILL.md", m)
        self.assertFalse(os.path.exists(
            os.path.join(self.skill, self_update.MANIFEST_NAME + ".tmp")))

    def test_manifest_never_protects_lunyu_entries(self):
        """清单里若脏数据包含 .lunyu 路径，也绝不删。"""
        write(os.path.join(self.skill, ".lunyu", "bugs.json"), "{}")
        seed_manifest(self.skill, ["SKILL.md", ".lunyu/bugs.json", ".git/config"])
        self_update.apply_update(self.skill, self.src, prune=True)
        self.assertTrue(os.path.isfile(os.path.join(self.skill, ".lunyu", "bugs.json")))

    def test_prune_chain_second_round(self):
        """连续两轮更新：第二轮能删掉第一轮写入、远端已移除的文件。"""
        write(os.path.join(self.src, "scripts", "a.py"), "a")
        self_update.apply_update(self.skill, self.src)
        os.remove(os.path.join(self.src, "scripts", "a.py"))
        _, removed = self_update.apply_update(self.skill, self.src)
        self.assertEqual(removed, ["scripts/a.py"])


class MirrorSourceTest(unittest.TestCase):
    """国内直连 GitHub 不稳，验证多源回退与镜像优先。"""

    def test_mirror_source_first(self):
        with patch.dict(os.environ, {"LUNYU_MIRROR": "https://gitee.com/mirror/lunyu"}):
            srcs = self_update._version_sources()
        self.assertEqual(srcs[0][0], "mirror")
        self.assertIn("gitee.com", srcs[0][1])

    def test_default_sources_include_cdn_and_api(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LUNYU_MIRROR", None)
            srcs = self_update._version_sources()
        names = [n for n, _ in srcs]
        self.assertIn("raw", names)
        self.assertIn("cdn", names)
        self.assertIn("api", names)

    def test_fetch_falls_back_when_first_source_fails(self):
        """第一个源挂掉时，应自动尝试下一个源。"""
        calls = []

        def fake_get(url, timeout=30):
            calls.append(url)
            if len(calls) == 1:
                raise RuntimeError("网络不可用")
            return b'---\nversion: "9.9.9"\n---\n'

        with patch.object(self_update, "http_get", side_effect=fake_get):
            v = self_update.fetch_remote_version()
        self.assertEqual(v, "9.9.9")
        self.assertGreaterEqual(len(calls), 2)

    def test_fetch_returns_empty_when_all_fail(self):
        with patch.object(self_update, "http_get", side_effect=RuntimeError("boom")):
            self.assertEqual(self_update.fetch_remote_version(), "")


class CheckModeTest(unittest.TestCase):
    """--check 只报告，绝不改文件。

    只 patch 网络出口 http_get：本地版本读取、远端 SKILL.md 解析、
    is_newer 版本比较全部真实执行（不再 patch __file__ / fetch_remote_version）。
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "scripts"))
        self.skill_md = os.path.join(self.tmp, "SKILL.md")
        write(self.skill_md, '---\nname: lunyu\nversion: "1.0.0"\n---\n')
        self.mod = load_self_update_at(self.tmp)

    def _run(self, argv, remote_text):
        """只 mock 网络，其余逻辑真跑。返回 (退出码, stdout)。"""
        with patch.object(self.mod, "http_get", return_value=remote_text.encode("utf-8")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = self.mod.main(argv)
        return rc, buf.getvalue()

    def test_check_reports_newer_and_does_not_modify(self):
        before = read(self.skill_md)
        rc, out = self._run(["--check"], '---\nname: lunyu\nversion: "2.0.0"\n---\n')
        self.assertEqual(rc, 2)
        # 本地版本真的从 SKILL.md 读出，远端版本真的从返回文本解析出来
        self.assertIn("本地版本: 1.0.0", out)
        self.assertIn("远端版本: 2.0.0", out)
        self.assertIn("1.0.0 -> 2.0.0", out)
        self.assertEqual(read(self.skill_md), before)  # 文件未被改动

    def test_up_to_date_returns_zero(self):
        rc, out = self._run([], '---\nname: lunyu\nversion: "1.0.0"\n---\n')
        self.assertEqual(rc, 0)
        self.assertIn("已是最新版本", out)

    def test_older_remote_never_downgrades(self):
        """远端更旧时版本比较必须判定为「不更新」（真实执行 is_newer）。"""
        rc, out = self._run([], '---\nname: lunyu\nversion: "0.9.0"\n---\n')
        self.assertEqual(rc, 0)
        self.assertIn("已是最新版本", out)

    def test_network_failure_returns_one(self):
        with patch.object(self.mod, "http_get", side_effect=RuntimeError("boom")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = self.mod.main([])
        self.assertEqual(rc, 1)
        self.assertIn("无法获取远端版本", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
