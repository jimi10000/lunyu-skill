#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
send_mail.py — 发送带附件的邮件（SMTP）

从风火轮音乐「每次交付必带 APK + md5」的邮件发包流程提炼的通用版本。
凭据全部走环境变量，脚本本身不保存任何账号信息。

用法（命令行）:
    python send_mail.py <附件路径> <邮件主题> <正文文件> [--verbose]

    --verbose  失败时打印完整异常（含 SMTP 服务器返回原文），默认关闭。

错误信息策略（安全）:
    smtplib 的异常文本在部分实现下会带上认证上下文（账号、auth 串等），
    而定时任务通常把 stdout 重定向进日志。因此失败时:
      - stdout 只输出异常类型名 + 一句不含敏感信息的提示
      - 详细信息走 stderr，并做脱敏处理（邮箱/凭据会被替换为占位符）
      - 只有显式加 --verbose 时才输出完整原文

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
import re
import sys
import traceback
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.header import Header

# 脱敏规则：邮箱地址 + 认证类 key=value
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RE_SECRET_KV = re.compile(
    r"(?i)(password|passwd|pwd|auth|token|secret|credential|code)\s*[:=]\s*\S+"
)


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
        part = MIMEApplication(f.read())
    # filename 用 RFC2231 编码(3 元组), 中文附件名直接塞 header 会乱码
    part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", fname))
    msg.attach(part)

    if use_ssl:
        server = smtplib.SMTP_SSL(server_host, server_port, timeout=30)
    else:
        server = smtplib.SMTP(server_host, server_port, timeout=30)
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


def _redact(text):
    """脱敏：把邮箱地址、认证类内容替换成占位符。

    smtplib 的异常文本可能带上账号/授权码等认证上下文，不能直接往日志打。
    """
    out = str(text)
    # 先按已知凭据原文替换（授权码可能不含 @，不会被邮箱规则命中）
    for key in ("SMTP_AUTH", "SMTP_PASSWORD", "SMTP_TOKEN"):
        secret = os.environ.get(key)
        if secret and len(secret) >= 4:
            out = out.replace(secret, "***")
    out = _RE_SECRET_KV.sub(lambda m: f"{m.group(1)}=***", out)
    out = _RE_EMAIL.sub("<email>", out)
    return out


def report_error(exc, verbose=False, stdout=None, stderr=None):
    """失败时对外汇报：stdout 只有异常类型，细节脱敏后进 stderr。"""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    print(f"发送失败: {type(exc).__name__}", file=stdout)
    if verbose:
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=stderr)
    else:
        detail = " ".join(_redact(exc).split())
        print(f"详情: {type(exc).__name__}: {detail}", file=stderr)
        print("提示: 加 --verbose 可查看完整异常（可能含敏感信息）", file=stderr)


def _parse_args(argv):
    """拆出 --verbose，其余按位置参数处理（保持原有调用方式不变）。"""
    verbose = False
    positional = []
    for arg in argv:
        if arg in ("--verbose", "-v"):
            verbose = True
        else:
            positional.append(arg)
    return verbose, positional


def main(argv=None):
    """入口。argv 为完整参数列表（含程序名），默认取 sys.argv。"""
    argv = list(sys.argv if argv is None else argv)
    verbose, args = _parse_args(argv[1:])
    if len(args) < 3:
        print("用法: python send_mail.py <附件路径> <邮件主题> <正文文件> [--verbose]")
        print("环境变量: SMTP_SERVER/SMTP_PORT/SMTP_SENDER/SMTP_AUTH/SMTP_RECEIVER/SMTP_SSL")
        return 1
    try:
        body_file = args[2]
        if not os.path.isfile(body_file):
            raise FileNotFoundError(f"正文文件不存在: {body_file}")
        with open(body_file, "r", encoding="utf-8") as f:
            body_text = f.read()
        send_mail(args[1], body_text, args[0])
        print("MAIL_SENT")
        return 0
    except Exception as e:
        report_error(e, verbose=verbose)
        return 1


if __name__ == "__main__":
    sys.exit(main())