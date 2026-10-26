#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""send_mail.py 单元测试

验证:
- 缺环境变量抛 RuntimeError
- 附件不存在抛 FileNotFoundError
- 非 SSL 分支调用 STARTTLS
- SSL 分支
- 收件人拒绝时抛 RuntimeError
"""
import base64
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


if __name__ == "__main__":
    unittest.main()