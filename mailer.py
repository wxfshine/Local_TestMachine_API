"""
邮件通知模块
- 通过 .env 中的 SMTP 配置发送邮件
- 单一公开函数：send_call_notification(...)
- 邮件发送失败不抛异常，仅记录日志（不阻塞业务）
"""

import os
import logging
import smtplib
import socket
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime
from typing import Any

try:
    from dotenv import load_dotenv
    load_dotenv()  # 默认从当前工作目录加载 .env
except Exception:  # dotenv 缺失或 .env 缺失时降级到系统环境变量
    pass

logger = logging.getLogger("test-trigger-service.mailer")

# 从环境变量读取邮件配置（缺失则记日志，不抛异常）
EMAIL_FROM = os.getenv("EMAIL_FROM", "").strip()
EMAIL_TO = os.getenv("EMAIL_TO", "").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "25") or "25")
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")


def _is_configured() -> bool:
    """检查邮件配置是否齐全"""
    return all([EMAIL_FROM, EMAIL_TO, SMTP_HOST, SMTP_USER, SMTP_PASSWORD])


def _build_subject(remote_ip: str, timestamp_str: str) -> str:
    return f"[AutoTestAPI] 触发通知 | {timestamp_str} | IP={remote_ip}"


def _build_body(
    timestamp_str: str,
    remote_ip: str,
    client_host: str,
    user_agent: str,
    method: str,
    path: str,
    task_info: Any,
    extra: dict | None = None,
) -> str:
    """构造邮件正文（纯文本 + HTML 兼容）"""
    task_info_str = ""
    try:
        task_info_str = json.dumps(task_info, ensure_ascii=False, indent=2)
    except Exception:
        task_info_str = str(task_info)

    extra_lines = ""
    if extra:
        for k, v in extra.items():
            extra_lines += f"<tr><td><b>{k}</b></td><td>{v}</td></tr>"

    html = f"""
<html><body style="font-family: -apple-system, Segoe UI, Arial, sans-serif;">
  <h2 style="color:#5b21b6;">AutoTestAPI 触发通知</h2>
  <p>本机主机名：<b>{socket.gethostname()}</b></p>
  <table cellspacing="6" cellpadding="6" border="1" style="border-collapse:collapse;border-color:#e5e7eb;">
    <tr><td><b>调用时间</b></td><td>{timestamp_str}</td></tr>
    <tr><td><b>调用方 IP</b></td><td>{remote_ip}</td></tr>
    <tr><td><b>主机名校验</b></td><td>{client_host or '-'}</td></tr>
    <tr><td><b>HTTP 方法</b></td><td>{method}</td></tr>
    <tr><td><b>请求路径</b></td><td>{path}</td></tr>
    <tr><td><b>User-Agent</b></td><td>{user_agent or '-'}</td></tr>
    {extra_lines}
  </table>
  <h3>请求体 (task_info)</h3>
  <pre style="background:#f5f5f5;padding:10px;border-radius:6px;">{task_info_str}</pre>
  <p style="color:#9ca3af;font-size:12px;">本邮件由 test_trigger.py 自动发送，无需回复。</p>
</body></html>
""".strip()

    text = (
        f"AutoTestAPI 触发通知\n"
        f"调用时间: {timestamp_str}\n"
        f"本机主机名: {socket.gethostname()}\n"
        f"调用方 IP: {remote_ip}\n"
        f"主机名校验: {client_host or '-'}\n"
        f"HTTP 方法: {method}\n"
        f"请求路径: {path}\n"
        f"User-Agent: {user_agent or '-'}\n"
        f"\n--- 请求体 (task_info) ---\n{task_info_str}\n"
    )
    return text, html


def _do_send(subject: str, text: str, html: str) -> None:
    """实际发送邮件（私有函数）"""
    if not _is_configured():
        logger.warning(
            "邮件配置不完整（EMAIL_FROM/EMAIL_TO/SMTP_HOST/SMTP_USER/SMTP_PASSWORD），"
            "跳过发送。检查 .env 文件。"
        )
        return

    recipients = [addr.strip() for addr in EMAIL_TO.split(",") if addr.strip()]
    if not recipients:
        logger.warning("EMAIL_TO 为空，跳过发送。")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("AutoTestAPI", EMAIL_FROM))
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    # 25 端口通常是明文 SMTP；公司内网常见
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
        server.ehlo()
        try:
            server.starttls()
            server.ehlo()
        except smtplib.SMTPNotSupportedError:
            # 25 端口明文无需 STARTTLS
            pass
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(EMAIL_FROM, recipients, msg.as_string())
    logger.info(f"通知邮件已发送至 {recipients}，主题: {subject}")


def send_call_notification(
    remote_ip: str,
    task_info: Any,
    *,
    method: str = "POST",
    path: str = "/api/trigger/auto-test",
    client_host: str = "",
    user_agent: str = "",
    extra: dict | None = None,
) -> None:
    """
    发送 API 被调用通知邮件（异常吞掉，仅记录日志）。
    调用方无需关心发送成败。
    """
    try:
        now = datetime.now()
        ts_str = now.strftime("%Y-%m-%d %H:%M:%S")
        subject = _build_subject(remote_ip, ts_str)
        text, html = _build_body(
            timestamp_str=ts_str,
            remote_ip=remote_ip,
            client_host=client_host,
            user_agent=user_agent,
            method=method,
            path=path,
            task_info=task_info,
            extra=extra,
        )
        _do_send(subject, text, html)
    except Exception as e:
        # 任何邮件错误都不能影响业务
        logger.error(f"发送通知邮件失败（已忽略，不影响业务）: {e}", exc_info=True)


def _build_completion_subject(status: str, timestamp_str: str, task_id: str) -> str:
    status_tag = {"success": "[成功]", "failed": "[失败]", "timeout": "[超时]", "error": "[异常]"}.get(status, "[未知]")
    return f"[AutoTestAPI] 执行结束 {status_tag} | {timestamp_str} | task={task_id}"


def _build_completion_body(
    timestamp_str: str,
    remote_ip: str,
    task_info: Any,
    result_code: int,
    result_msg: str,
    stdout: str,
    stderr: str,
    duration_seconds: float,
    extra: dict | None = None,
) -> tuple[str, str]:
    task_id = str(task_info.get("task_id", "-"))
    remark = str(task_info.get("remark", "-"))

    duration_str = ""
    if duration_seconds >= 3600:
        hours = int(duration_seconds // 3600)
        minutes = int((duration_seconds % 3600) // 60)
        duration_str = f"{hours}小时{minutes}分钟"
    elif duration_seconds >= 60:
        duration_str = f"{int(duration_seconds // 60)}分钟{int(duration_seconds % 60)}秒"
    else:
        duration_str = f"{duration_seconds:.1f}秒"

    status_color = "#10b981" if result_code == 200 else "#ef4444"

    extra_lines = ""
    if extra:
        for k, v in extra.items():
            extra_lines += f"<tr><td><b>{k}</b></td><td>{v}</td></tr>"

    html = f"""
<html><body style="font-family: -apple-system, Segoe UI, Arial, sans-serif;">
  <h2 style="color:#5b21b6;">AutoTestAPI 执行结束通知</h2>
  <p>本机主机名：<b>{socket.gethostname()}</b></p>
  <table cellspacing="6" cellpadding="6" border="1" style="border-collapse:collapse;border-color:#e5e7eb;">
    <tr><td><b>结束时间</b></td><td>{timestamp_str}</td></tr>
    <tr><td><b>调用方 IP</b></td><td>{remote_ip}</td></tr>
    <tr><td><b>任务 ID</b></td><td>{task_id}</td></tr>
    <tr><td><b>任务备注</b></td><td>{remark}</td></tr>
    <tr><td><b>执行耗时</b></td><td>{duration_str}</td></tr>
    <tr><td><b>结果码</b></td><td><span style="color:{status_color};font-weight:bold;">{result_code}</span></td></tr>
    <tr><td><b>结果消息</b></td><td><span style="color:{status_color};font-weight:bold;">{result_msg}</span></td></tr>
    {extra_lines}
  </table>
  
  <h3>标准输出 (stdout)</h3>
  <pre style="background:#f5f5f5;padding:10px;border-radius:6px;max-height:300px;overflow:auto;">{stdout[:3000]}{'...(truncated)' if len(stdout) > 3000 else ''}</pre>
  
  <h3>错误输出 (stderr)</h3>
  <pre style="background:#fef2f2;padding:10px;border-radius:6px;max-height:300px;overflow:auto;color:#991b1b;">{stderr[:3000]}{'...(truncated)' if len(stderr) > 3000 else ''}</pre>
  
  <p style="color:#9ca3af;font-size:12px;">本邮件由 test_trigger.py 自动发送，无需回复。</p>
</body></html>
""".strip()

    text = (
        f"AutoTestAPI 执行结束通知\n"
        f"结束时间: {timestamp_str}\n"
        f"本机主机名: {socket.gethostname()}\n"
        f"调用方 IP: {remote_ip}\n"
        f"任务 ID: {task_id}\n"
        f"任务备注: {remark}\n"
        f"执行耗时: {duration_str}\n"
        f"结果码: {result_code}\n"
        f"结果消息: {result_msg}\n"
        f"\n--- 标准输出 (stdout) ---\n{stdout[:3000]}{'...(truncated)' if len(stdout) > 3000 else ''}\n"
        f"\n--- 错误输出 (stderr) ---\n{stderr[:3000]}{'...(truncated)' if len(stderr) > 3000 else ''}\n"
    )
    return text, html


def send_completion_notification(
    remote_ip: str,
    task_info: Any,
    result_code: int,
    result_msg: str,
    stdout: str = "",
    stderr: str = "",
    duration_seconds: float = 0.0,
    extra: dict | None = None,
) -> None:
    """
    发送 API 执行结束通知邮件（异常吞掉，仅记录日志）。
    无论成功、失败、超时、异常都会发送。
    """
    try:
        now = datetime.now()
        ts_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        status = "success" if result_code == 200 else \
                 "timeout" if result_code == -11 else \
                 "failed" if result_code < 0 else "success"
        subject = _build_completion_subject(status, ts_str, str(task_info.get("task_id", "-")))
        
        text, html = _build_completion_body(
            timestamp_str=ts_str,
            remote_ip=remote_ip,
            task_info=task_info,
            result_code=result_code,
            result_msg=result_msg,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration_seconds,
            extra=extra,
        )
        _do_send(subject, text, html)
    except Exception as e:
        # 任何邮件错误都不能影响业务
        logger.error(f"发送执行结束通知邮件失败（已忽略，不影响业务）: {e}", exc_info=True)
