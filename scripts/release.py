#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
release.py — 双端发布：GitHub + Gitee Release/附件 + update.json 更新

从风火轮音乐「双推发布链路」提炼的通用版本：
- 创建 Release（已存在则复用，幂等）
- 上传 APK 等附件（同名先删，幂等）
- 更新 update.json 到双端 main 分支（可选）

所有凭据走环境变量，脚本内零硬编码。

用法:
    python release.py --apk path/to/app.apk --version v1.2.3 \
        --name "产品名 v1.2.3" --desc "发布说明" \
        --update-json path/to/update.json \
        --platform github --platform gitee

    # 只发布 GitHub，不带 update.json:
    python release.py --apk app.apk --version v1.2.3 --name "..." --platform github

环境变量:
    GITHUB_USER     GitHub 用户名（必填）
    GITHUB_TOKEN    GitHub PAT（repo 权限，必填）
    GITHUB_REPO     GitHub 仓库名（必填）
    GITEE_USER      Gitee 用户名（如用 Gitee 必填）
    GITEE_TOKEN     Gitee 访问令牌（如用 Gitee 必填）
    GITEE_REPO      Gitee 仓库名（如用 Gitee 必填）

退出码: 0=成功 / 1=失败
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def req(method, url, data=None, headers=None, timeout=30):
    r = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        body = resp.read()
        return resp.status, (json.loads(body) if body else {})


def req_raw(method, url, data=None, headers=None, timeout=60):
    r = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.status, resp.read()


class Publisher:
    """单端发布器：创建/复用 Release、传附件、更新 update.json。"""

    def __init__(self, platform, user, repo, token, branch="main"):
        self.platform = platform
        self.user = user
        self.repo = repo
        self.token = token
        self.branch = branch

    # ---------- 平台差异 ----------
    def _api_base(self):
        return "https://gitee.com/api/v5" if self.platform == "gitee" else "https://api.github.com"

    def _auth(self):
        if self.platform == "gitee":
            # Gitee API v5 不认 HTTP header 鉴权, access_token 必须走 query/body,
            # 由 _url() 统一拼进 query; 这里返回空头
            return {}
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"}

    def _url(self, url):
        """Gitee 把 access_token 拼进 query(已有 query 则用 & 续接); GitHub 原样返回。"""
        if self.platform != "gitee":
            return url
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}access_token={urllib.parse.quote(self.token)}"

    def _release_url(self, rid=None):
        base = f"{self._api_base()}/repos/{self.user}/{self.repo}/releases"
        if rid is not None:
            return f"{base}/{rid}"
        return base

    def _asset_list_url(self, rid):
        if self.platform == "gitee":
            return f"{self._release_url(rid)}/attach_files"
        return f"{self._release_url(rid)}/assets"

    def _asset_delete_url(self, rid, aid):
        if self.platform == "gitee":
            return f"{self._release_url(rid)}/attach_files/{aid}"
        # GitHub 资产删除：DELETE /repos/{owner}/{repo}/releases/assets/{asset_id}
        # 资产 ID 全局唯一，不需要 release id；用 release 路径会 404
        return f"{self._api_base()}/repos/{self.user}/{self.repo}/releases/assets/{aid}"

    def _asset_upload(self, rid, file_path):
        fname = os.path.basename(file_path)
        if self.platform == "gitee":
            url = self._url(f"{self._release_url(rid)}/attach_files")
            with open(file_path, "rb") as f:
                payload = f.read()
            boundary = "----lunyuBoundary7e3a"
            body = (b"--" + boundary.encode() + b"\r\n"
                    + f'Content-Disposition: form-data; name="file"; filename="{fname}"\r\n'.encode()
                    + b"Content-Type: application/octet-stream\r\n\r\n"
                    + payload + b"\r\n--" + boundary.encode() + b"--\r\n")
            st, _ = req_raw("POST", url, data=body,
                            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                            timeout=180)
            return st
        # 文件名必须 urlencode, 带空格/中文的文件名否则 400
        url = f"https://uploads.github.com/repos/{self.user}/{self.repo}/releases/{rid}/assets?name={urllib.parse.quote(fname)}"
        with open(file_path, "rb") as f:
            payload = f.read()
        st, _ = req_raw("POST", url, data=payload,
                        headers={**self._auth(), "Content-Type": "application/octet-stream"},
                        timeout=180)
        return st

    # ---------- 核心操作 ----------
    def create_release(self, version, name, desc):
        """创建 Release，已存在则复用。返回 release id。"""
        create = json.dumps({
            "tag_name": version,
            "name": name,
            "body": desc,
            "prerelease": False,
            "target_commitish": self.branch,
        }).encode("utf-8")
        try:
            st, j = req("POST", self._url(self._release_url()), data=create,
                        headers={**self._auth(), "Content-Type": "application/json"})
            return j["id"]
        except urllib.error.HTTPError as e:
            if e.code in (409, 422):
                st, j = req("GET", self._url(f"{self._release_url()}/tags/{version}"),
                            headers=self._auth())
                return j["id"]
            raise

    def upload_asset(self, rid, file_path):
        """上传附件，同名先删。"""
        fname = os.path.basename(file_path)
        st, arr = req("GET", self._url(self._asset_list_url(rid)), headers=self._auth())
        for a in (arr or []):
            if a.get("name") == fname:
                try:
                    req("DELETE", self._url(self._asset_delete_url(rid, a["id"])),
                        headers=self._auth())
                except Exception as e:
                    print(f"  {self.platform} 删旧附件失败(忽略): {e}")
        return self._asset_upload(rid, file_path)

    def put_update_json(self, update_json_path, version):
        """把 update.json 内容以 base64 写到仓库 main 分支（幂等）。"""
        url = f"{self._api_base()}/repos/{self.user}/{self.repo}/contents/update.json"
        # GET 必须带 ref, 否则 GitHub 只查默认分支, 非默认分支时 sha 会取错
        get_url = f"{url}?ref={self.branch}"
        put_url = url
        if self.platform == "gitee":
            get_url = self._url(get_url)
            put_url = self._url(url)
        try:
            st, j = req("GET", get_url, headers=self._auth())
            sha = j.get("sha")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                sha = None
            else:
                raise
        with open(update_json_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        body = json.dumps({
            "message": f"chore: publish update.json {version}",
            "content": b64,
            "branch": self.branch,
            **({"sha": sha} if sha else {}),
        }).encode("utf-8")
        st, j = req("PUT", put_url, data=body,
                    headers={**self._auth(), "Content-Type": "application/json"})
        return st


def main():
    ap = argparse.ArgumentParser(description="双端发布：GitHub + Gitee Release/附件/update.json")
    ap.add_argument("--apk", required=True, help="要发布的 APK/附件路径")
    ap.add_argument("--version", required=True, help="版本号，如 v1.2.3")
    ap.add_argument("--name", required=True, help="Release 名称，如 产品名 v1.2.3")
    ap.add_argument("--desc", default="自动发布", help="Release 说明")
    ap.add_argument("--update-json", help="update.json 路径（可选）")
    ap.add_argument("--platform", action="append", choices=["github", "gitee"],
                    help="发布平台，可重复指定；不指定默认 github")
    ap.add_argument("--branch", default="main", help="目标分支")
    args = ap.parse_args()

    platforms = args.platform or ["github"]
    ok = True
    for p in platforms:
        user = os.environ.get(f"{p.upper()}_USER", "")
        repo = os.environ.get(f"{p.upper()}_REPO", "")
        token = os.environ.get(f"{p.upper()}_TOKEN", "")
        if not user or not repo or not token:
            print(f"错误: 缺少 {p.upper()}_USER / {p.upper()}_REPO / {p.upper()}_TOKEN 环境变量")
            ok = False
            continue
        pub = Publisher(p, user, repo, token, branch=args.branch)
        try:
            rid = pub.create_release(args.version, args.name, args.desc)
            print(f"[{p}] Release id={rid}")
            st = pub.upload_asset(rid, args.apk)
            print(f"[{p}] 附件上传 {st}")
            if args.update_json:
                st2 = pub.put_update_json(args.update_json, args.version)
                print(f"[{p}] update.json PUT {st2}")
        except Exception as e:
            print(f"[{p}] 发布失败: {e}")
            ok = False

    print("PUBLISH_DONE" if ok else "PUBLISH_FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()