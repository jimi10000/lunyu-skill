#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""release.py 单元测试

验证:
- req/req_raw 基本 HTTP 封装
- Publisher 平台差异: API base、auth 头、资产删除 URL（GitHub 用 releases/assets/{id}）
- create_release 409/422 时复用已有 release
- upload_asset 同名先删
- put_update_json 404 时无 sha，有内容则带 sha
"""
import base64
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import release


class PublisherUrlTest(unittest.TestCase):
    def test_api_base(self):
        gh = release.Publisher("github", "u", "r", "t")
        self.assertEqual(gh._api_base(), "https://api.github.com")
        gi = release.Publisher("gitee", "u", "r", "t")
        self.assertEqual(gi._api_base(), "https://gitee.com/api/v5")

    def test_auth_headers(self):
        gh = release.Publisher("github", "u", "r", "tok")
        self.assertEqual(gh._auth(), {
            "Authorization": "Bearer tok",
            "Accept": "application/vnd.github+json",
        })
        gi = release.Publisher("gitee", "u", "r", "tok")
        self.assertEqual(gi._auth(), {"access_token": "tok"})

    def test_asset_delete_url(self):
        # 关键回归: GitHub 资产删除用 releases/assets/{id}，不是 release 路径
        gh = release.Publisher("github", "u", "r", "t")
        self.assertEqual(
            gh._asset_delete_url(123, 456),
            "https://api.github.com/repos/u/r/releases/assets/456",
        )
        gi = release.Publisher("gitee", "u", "r", "t")
        self.assertEqual(
            gi._asset_delete_url(123, 456),
            "https://gitee.com/api/v5/repos/u/r/releases/123/attach_files/456",
        )

    def test_asset_list_url(self):
        gh = release.Publisher("github", "u", "r", "t")
        self.assertEqual(gh._asset_list_url(1), "https://api.github.com/repos/u/r/releases/1/assets")
        gi = release.Publisher("gitee", "u", "r", "t")
        self.assertEqual(gi._asset_list_url(1), "https://gitee.com/api/v5/repos/u/r/releases/1/attach_files")


class CreateReleaseTest(unittest.TestCase):
    def test_created(self):
        pub = release.Publisher("github", "u", "r", "t")
        with patch.object(release, "req", return_value=(201, {"id": 99})) as m:
            rid = pub.create_release("v1.0.0", "name", "desc")
        self.assertEqual(rid, 99)
        # 确认 URL 和 body（data 是关键字参数）
        args, kwargs = m.call_args
        self.assertEqual(args[0], "POST")
        self.assertIn("/releases", args[1])
        body = json.loads(kwargs["data"])
        self.assertEqual(body["tag_name"], "v1.0.0")
        self.assertEqual(body["name"], "name")
        self.assertEqual(body["body"], "desc")

    def test_conflict_reuses_existing(self):
        pub = release.Publisher("github", "u", "r", "t")
        err = __import__("urllib.error", fromlist=["HTTPError"])
        http_err = err.HTTPError("url", 409, "Conflict", {}, None)
        with patch.object(release, "req") as m:
            m.side_effect = [http_err, (200, {"id": 55})]
            rid = pub.create_release("v1.0.0", "name", "desc")
        self.assertEqual(rid, 55)


class UploadAssetTest(unittest.TestCase):
    def test_same_name_deleted_before_upload(self):
        pub = release.Publisher("github", "u", "r", "t")
        tmp = tempfile.mkdtemp()
        apk = os.path.join(tmp, "app.apk")
        with open(apk, "wb") as f:
            f.write(b"apkdata")
        # GET 返回已有同名资产
        with patch.object(release, "req", return_value=(200, [{"name": "app.apk", "id": 7}])) as m, \
             patch.object(release.Publisher, "_asset_upload", return_value=201) as up:
            st = pub.upload_asset(1, apk)
        self.assertEqual(st, 201)
        # 验证 DELETE 被调用且 URL 是 releases/assets/7
        delete_call = [c for c in m.call_args_list if c.args[0] == "DELETE"]
        self.assertEqual(len(delete_call), 1)
        self.assertIn("/releases/assets/7", delete_call[0].args[1])
        up.assert_called_once_with(1, apk)


class PutUpdateJsonTest(unittest.TestCase):
    def test_no_existing_file(self):
        pub = release.Publisher("github", "u", "r", "t")
        tmp = tempfile.mkdtemp()
        uj = os.path.join(tmp, "update.json")
        with open(uj, "w", encoding="utf-8") as f:
            json.dump({"version": "v1.0.0"}, f)
        err = __import__("urllib.error", fromlist=["HTTPError"])
        not_found = err.HTTPError("url", 404, "Not Found", {}, None)
        with patch.object(release, "req") as m:
            m.side_effect = [not_found, (201, {"content": {}})]
            st = pub.put_update_json(uj, "v1.0.0")
        self.assertEqual(st, 201)
        # 确认 PUT body 没有 sha（data 是关键字参数）
        put_call = [c for c in m.call_args_list if c.args[0] == "PUT"][0]
        body = json.loads(put_call.kwargs["data"])
        self.assertNotIn("sha", body)
        self.assertIn("branch", body)
        # base64 内容正确
        decoded = base64.b64decode(body["content"]).decode("utf-8")
        self.assertIn("v1.0.0", decoded)

    def test_existing_file_with_sha(self):
        pub = release.Publisher("github", "u", "r", "t")
        tmp = tempfile.mkdtemp()
        uj = os.path.join(tmp, "update.json")
        with open(uj, "w", encoding="utf-8") as f:
            f.write("{}")
        with patch.object(release, "req", side_effect=[
            (200, {"sha": "abc123"}),
            (200, {"content": {}}),
        ]) as m:
            st = pub.put_update_json(uj, "v1.0.0")
        put_call = [c for c in m.call_args_list if c.args[0] == "PUT"][0]
        body = json.loads(put_call.kwargs["data"])
        self.assertEqual(body["sha"], "abc123")


class ReqTest(unittest.TestCase):
    def _mock_resp(self, body):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = body
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        return mock_resp

    def test_req_parses_json(self):
        mock_resp = self._mock_resp(b'{"id": 1}')
        with patch.object(release.urllib.request, "urlopen", return_value=mock_resp):
            st, j = release.req("GET", "https://example.com")
        self.assertEqual(st, 200)
        self.assertEqual(j, {"id": 1})

    def test_req_raw_bytes(self):
        mock_resp = self._mock_resp(b"raw")
        with patch.object(release.urllib.request, "urlopen", return_value=mock_resp):
            st, data = release.req_raw("POST", "https://example.com")
        self.assertEqual(st, 200)
        self.assertEqual(data, b"raw")


if __name__ == "__main__":
    unittest.main()