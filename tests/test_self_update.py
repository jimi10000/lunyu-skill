# -*- coding: utf-8 -*-
"""self_update.py 单元测试。

重点覆盖：
  - parse_version：顶层 version 优先、metadata 子层回退（这是之前 .sh 版本的坑）
  - vtuple / is_newer：语义化版本比较，v 前缀兼容
  - find_skill_root：Release 附件与分支归档两种 zip 结构
  - apply_update：覆盖写入 + 保留 .lunyu 数据 + 清理旧文件
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import self_update  # noqa: E402


def write(path, content):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


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
        """远端已删除的旧文件应被清理（.sh 版因无 rsync 做不到）。"""
        write(os.path.join(self.skill, "scripts", "old_tool.py"), "x")
        write(os.path.join(self.skill, "SKILL.md"), '---\nversion: "1.0.0"\n---\n')
        write(os.path.join(self.src, "SKILL.md"), '---\nversion: "1.1.4"\n---\n')
        _, removed = self_update.apply_update(self.skill, self.src, prune=True)
        self.assertIn("scripts/old_tool.py", removed)
        self.assertFalse(os.path.exists(os.path.join(self.skill, "scripts", "old_tool.py")))

    def test_no_prune_keeps_files(self):
        write(os.path.join(self.skill, "scripts", "old_tool.py"), "x")
        write(os.path.join(self.skill, "SKILL.md"), '---\nversion: "1.0.0"\n---\n')
        write(os.path.join(self.src, "SKILL.md"), '---\nversion: "1.1.4"\n---\n')
        self_update.apply_update(self.skill, self.src, prune=False)
        self.assertTrue(os.path.exists(os.path.join(self.skill, "scripts", "old_tool.py")))


if __name__ == "__main__":
    unittest.main(verbosity=2)


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
    """--check 只报告，绝不改文件。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.scripts = os.path.join(self.tmp, "scripts")
        os.makedirs(self.scripts)
        write(os.path.join(self.tmp, "SKILL.md"), '---\nversion: "1.0.0"\n---\n')

    def _run(self, argv):
        with patch.object(self_update, "__file__",
                          os.path.join(self.scripts, "self_update.py")), \
             patch.object(self_update, "fetch_remote_version", return_value="2.0.0"):
            return self_update.main(argv)

    def test_check_reports_and_does_not_modify(self):
        rc = self._run(["--check"])
        self.assertEqual(rc, 2)
        before = open(os.path.join(self.tmp, "SKILL.md"), encoding="utf-8").read()
        self.assertIn("1.0.0", before)  # 文件未被改动

    def test_up_to_date_returns_zero(self):
        with patch.object(self_update, "__file__",
                          os.path.join(self.scripts, "self_update.py")), \
             patch.object(self_update, "fetch_remote_version", return_value="1.0.0"):
            rc = self_update.main([])
        self.assertEqual(rc, 0)
