#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
send_mail.py — 发送带附件的邮件（SMTP）

从风火轮音乐「每次交付必带 APK + md5」的邮件发包流程提炼的通用版本。
凭据全部走环境变量，脚本本身不保存任何账号信息。

用法（命令行）:
    python send_mail.py <附件路径> <邮件主题> <正文文件>

环境变量:
    SMTP_SERVER     SMTP 服务器，默认 smtp.qq.com
    SMTP_PORT       SMTP 端口，默认 465（SSL）/ 587（非 SSL）
    SMTP_SENDER     发件人邮箱（必填）
    SMTP_AUTH       授权码/密码（必填，QQ 邮箱用授权码而非登录密码）
    SMTP_RECEIVER   收件人邮箱，多个用逗号分隔（必填）
    SMTP_SSL        是否 SSL，默认 true；设为 false 则用普通 SMTP+STARTTLS

退出码: 0=成功 / 1=失败
"""
import os
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.header import Header


def send_mail(subject, body, attachment_path):
    """发送带附件的邮件。

    Args:
        subject: 邮件主题
        body: 邮件正文（纯文本）
        attachment_path: 附件文件路径
    Returns:
        True
    """
    if not os.path.isfile(attachment_path):
        raise FileNotFoundError(f"附件不存在: {attachment_path}")

    server_host = os.environ.get("SMTP_SERVER", "smtp.qq.com")
    use_ssl = os.environ.get("SMTP_SSL", "true").lower() != "false"
    server_port = int(os.environ.get("SMTP_PORT", "465" if use_ssl else "587"))
    sender = os.environ.get("SMTP_SENDER", "")
    auth = os.environ.get("SMTP_AUTH", "")
    receivers = [r.strip() for r in os.environ.get("SMTP_RECEIVER", "").split(",") if r.strip()]
    use_ssl = os.environ.get("SMTP_SSL", "true").lower() != "false"

    if not sender or not auth or not receivers:
        raise RuntimeError(
            "缺少 SMTP 环境变量：请设置 SMTP_SENDER / SMTP_AUTH / SMTP_RECEIVER"
        )

    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = ", ".join(receivers)
    msg["Subject"] = Header(subject, "utf-8")
    msg.attach(MIMEText(body, "plain", "utf-8"))

    fname = os.path.basename(attachment_path)
    with open(attachment_path, "rb") as f:
        part = MIMEApplication(f.read(), Name=fname)
    part["Content-Disposition"] = f'attachment; filename="{fname}"'
    msg.attach(part)

    if use_ssl:
        server = smtplib.SMTP_SSL(server_host, server_port)
    else:
        server = smtplib.SMTP(server_host, server_port)
        server.ehlo()
        server.starttls()
        server.ehlo()
    try:
        server.login(sender, auth)
        refused = server.sendmail(sender, receivers, msg.as_string())
        if refused:
            raise RuntimeError(f"部分收件人被拒绝: {refused}")
    finally:
        server.quit()
    return True


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("用法: python send_mail.py <附件路径> <邮件主题> <正文文件>")
        print("环境变量: SMTP_SERVER/SMTP_PORT/SMTP_SENDER/SMTP_AUTH/SMTP_RECEIVER/SMTP_SSL")
        sys.exit(1)
    try:
        with open(sys.argv[3], "r", encoding="utf-8") as f:
            body_text = f.read()
        send_mail(sys.argv[2], body_text, sys.argv[1])
        print("MAIL_SENT")
    except Exception as e:
        print(f"发送失败: {e}")
        sys.exit(1)