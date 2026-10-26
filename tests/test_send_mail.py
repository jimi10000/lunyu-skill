#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""send_mail.py 单元测试

验证:
- 缺环境变量抛 RuntimeError
- 附件不存在抛 FileNotFoundError
- 非 SSL 分支调用 STARTTLS
- SSL 分支
- 收件人拒绝时抛 RuntimeError
- CLI 失败输出脱敏：stdout 只有异常类型，细节进 stderr 且凭据被打码
"""
import base64
import contextlib
import io
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import send_mail


class FakeServer:
    """模拟 SMTP 服务器。"""
    def __init__(self, refused=None):
        self.refused = refused or {}
        self.login_called = False
        self.quit_called = False
        self.ehlo_count = 0
        self.starttls_count = 0
        self.sent = None

    def ehlo(self):
        self.ehlo_count += 1

    def starttls(self):
        self.starttls_count += 1

    def login(self, sender, auth):
        self.login_called = True
        self.sender = sender
        self.auth = auth

    def sendmail(self, sender, receivers, msg):
        self.sent = (sender, receivers, msg)
        return self.refused

    def quit(self):
        self.quit_called = True


class SendMailTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.att = os.path.join(self.tmp, "app.apk")
        with open(self.att, "wb") as f:
            f.write(b"PK\x03\x04fakeapk")

        self.env = {
            "SMTP_SENDER": "me@example.com",
            "SMTP_AUTH": "secret",
            "SMTP_RECEIVER": "you@example.com",
        }

    def apply_env(self):
        for k, v in self.env.items():
            os.environ[k] = v

    def tearDown(self):
        for k in ("SMTP_SENDER", "SMTP_AUTH", "SMTP_RECEIVER", "SMTP_SERVER",
                  "SMTP_PORT", "SMTP_SSL"):
            os.environ.pop(k, None)

    def test_missing_env_raises(self):
        os.environ.pop("SMTP_SENDER", None)
        os.environ.pop("SMTP_AUTH", None)
        os.environ.pop("SMTP_RECEIVER", None)
        with self.assertRaises(RuntimeError):
            send_mail.send_mail("主题", "正文", self.att)

    def test_missing_attachment_raises(self):
        self.apply_env()
        with self.assertRaises(FileNotFoundError):
            send_mail.send_mail("主题", "正文", os.path.join(self.tmp, "nope.apk"))

    def test_non_ssl_starttls(self):
        self.env["SMTP_SSL"] = "false"
        self.apply_env()
        fake = FakeServer()
        with patch.object(send_mail.smtplib, "SMTP", return_value=fake) as smtp:
            ok = send_mail.send_mail("主题", "正文", self.att)
        self.assertTrue(ok)
        self.assertEqual(fake.ehlo_count, 2)
        self.assertEqual(fake.starttls_count, 1)
        self.assertTrue(fake.login_called)
        self.assertTrue(fake.quit_called)
        # 附件内容以 base64 形式包含在消息里，解码后应含原始字节
        raw = fake.sent[2].encode()
        self.assertIn(base64.b64encode(b"PK\x03\x04fakeapk"), raw)

    def test_ssl(self):
        self.apply_env()  # 默认 SSL
        fake = FakeServer()
        with patch.object(send_mail.smtplib, "SMTP_SSL", return_value=fake) as smtp:
            ok = send_mail.send_mail("主题", "正文", self.att)
        self.assertTrue(ok)
        self.assertEqual(fake.ehlo_count, 0)
        self.assertEqual(fake.starttls_count, 0)

    def test_refused_raises(self):
        self.apply_env()
        fake = FakeServer(refused={"bad@example.com": (550, "reject")})
        with patch.object(send_mail.smtplib, "SMTP_SSL", return_value=fake):
            with self.assertRaises(RuntimeError) as ctx:
                send_mail.send_mail("主题", "正文", self.att)
        self.assertIn("拒绝", str(ctx.exception))

    def test_chinese_attachment_filename_encoded(self):
        """回归: 中文附件名必须 RFC2231 编码, 直接塞 header 会乱码。"""
        self.apply_env()
        fake = FakeServer()
        att = os.path.join(self.tmp, "风火轮.apk")
        with open(att, "wb") as f:
            f.write(b"x")
        with patch.object(send_mail.smtplib, "SMTP_SSL", return_value=fake):
            ok = send_mail.send_mail("主题", "正文", att)
        self.assertTrue(ok)
        raw = fake.sent[2]
        self.assertIn("filename*=", raw)
        self.assertNotIn('filename="风火轮', raw)


class ReportErrorTest(unittest.TestCase):
    """回归: 异常信息不得携带认证上下文进日志(stdout)。"""

    SECRET = "SuperSecretAuthCode123"

    def setUp(self):
        self.env = {
            "SMTP_SENDER": "me@corp.example.com",
            "SMTP_AUTH": self.SECRET,
            "SMTP_RECEIVER": "boss@vip.example.com",
        }
        for k, v in self.env.items():
            os.environ[k] = v

    def tearDown(self):
        for k in self.env:
            os.environ.pop(k, None)

    def _capture(self, exc, verbose):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            send_mail.report_error(exc, verbose=verbose, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_stdout_only_carries_exception_type(self):
        exc = RuntimeError(f"535 auth failed for me@corp.example.com password={self.SECRET}")
        out, err = self._capture(exc, verbose=False)
        self.assertEqual(out.strip(), "发送失败: RuntimeError")
        self.assertNotIn(self.SECRET, out)
        self.assertNotIn(self.SECRET, err)
        self.assertNotIn("me@corp.example.com", out)
        self.assertNotIn("me@corp.example.com", err)

    def test_detail_goes_to_stderr_and_is_redacted(self):
        exc = RuntimeError(f"535 auth failed for me@corp.example.com password={self.SECRET}")
        out, err = self._capture(exc, verbose=False)
        self.assertEqual(out.count("\n"), 1)          # stdout 只有一行
        self.assertIn("RuntimeError", err)
        self.assertIn("<email>", err)                 # 邮箱被打码
        self.assertIn("***", err)                     # 凭据被打码

    def test_verbose_shows_full_exception_on_stderr(self):
        exc = RuntimeError(f"535 auth failed password={self.SECRET}")
        out, err = self._capture(exc, verbose=True)
        self.assertEqual(out.strip(), "发送失败: RuntimeError")
        self.assertIn(self.SECRET, err)               # 显式开关才给原文
        self.assertNotIn(self.SECRET, out)

    def test_redact_helper(self):
        text = "login me@corp.example.com failed, password=abcd1234, auth: xyzQ"
        out = send_mail._redact(text)
        self.assertNotIn("me@corp.example.com", out)
        self.assertIn("<email>", out)
        self.assertIn("password=***", out)
        self.assertIn("auth=***", out)


class MainCliTest(unittest.TestCase):
    """回归: CLI 入口保持原有调用方式，并支持 --verbose。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.att = os.path.join(self.tmp, "app.apk")
        with open(self.att, "wb") as f:
            f.write(b"x")
        self.body = os.path.join(self.tmp, "body.txt")
        with open(self.body, "w", encoding="utf-8") as f:
            f.write("hello")
        self.env = {
            "SMTP_SENDER": "me@example.com",
            "SMTP_AUTH": "secret",
            "SMTP_RECEIVER": "you@example.com",
        }
        for k, v in self.env.items():
            os.environ[k] = v

    def tearDown(self):
        for k in self.env:
            os.environ.pop(k, None)

    def _argv(self, *tail):
        return ["send_mail.py", self.att, "主题", self.body, *tail]

    def _run(self, *tail, server=None, exc=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            if server is not None:
                p = patch.object(send_mail.smtplib, "SMTP_SSL", return_value=server)
            else:
                p = patch.object(send_mail.smtplib, "SMTP_SSL", side_effect=exc)
            with p:
                rc = send_mail.main(self._argv(*tail))
        return rc, out.getvalue(), err.getvalue()

    def test_too_few_args_returns_1(self):
        self.assertEqual(send_mail.main(["send_mail.py"]), 1)

    def test_success_prints_mail_sent(self):
        rc, out, err = self._run(server=FakeServer())
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "MAIL_SENT")

    def test_failure_exit_code_and_masked_output(self):
        exc = RuntimeError("535 bad auth for me@example.com password=secret")
        rc, out, err = self._run(exc=exc)
        self.assertEqual(rc, 1)
        self.assertEqual(out.strip(), "发送失败: RuntimeError")
        self.assertIn("<email>", err)

    def test_verbose_flag_parsed_and_positionals_kept(self):
        verbose, args = send_mail._parse_args(["a", "--verbose", "b", "c"])
        self.assertTrue(verbose)
        self.assertEqual(args, ["a", "b", "c"])


if __name__ == "__main__":
    unittest.main()