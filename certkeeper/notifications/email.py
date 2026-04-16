"""SMTP 邮件通知器。"""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import TYPE_CHECKING

from certkeeper.notifications.base import Notifier, ReminderSummary

if TYPE_CHECKING:
    from certkeeper.core.manager import ApplySummary

logger = logging.getLogger(__name__)


class EmailNotifier(Notifier):
    """通过 SMTP 发送邮件通知。"""

    def validate_config(self) -> list[str]:
        errors: list[str] = []
        settings = self.config.settings
        for field_name in ("host", "sender", "recipients"):
            if field_name not in settings or not settings[field_name]:
                errors.append(f"{field_name} is required")
        return errors

    # ── 操作结果通知 ──

    def notify(self, summary: ApplySummary) -> None:
        if not summary.results:
            return

        has_errors = any(r.errors for r in summary.results)
        subject = "[CertKeeper] 证书处理失败" if has_errors else "[CertKeeper] 证书处理成功"
        body = self._build_result_body(summary)
        self._send_email(subject, body)

    # ── 到期提醒 ──

    def notify_reminder(self, reminder_summary: ReminderSummary) -> None:
        if not reminder_summary.reminders:
            return

        subject = "[CertKeeper] 证书即将到期提醒"
        body = self._build_reminder_body(reminder_summary)
        self._send_email(subject, body)

    # ── 邮件内容构建 ──

    def _build_result_body(self, summary: ApplySummary) -> str:
        lines = ["证书处理结果汇总：", ""]
        for result in summary.results:
            status_icon = "成功" if not result.errors else "失败"
            lines.append(f"域名: {result.domain}")
            lines.append(f"  状态: {status_icon}")
            if result.renewed:
                lines.append(f"  续期: 是")
            if result.deployed_targets:
                lines.append(f"  部署到: {', '.join(result.deployed_targets)}")
            if result.errors:
                lines.append(f"  错误: {'; '.join(result.errors)}")
            lines.append("")
        return "\n".join(lines)

    def _build_reminder_body(self, reminder_summary: ReminderSummary) -> str:
        renewal_days = reminder_summary.renewal_days
        lines = ["以下证书即将到期：", ""]
        for reminder in reminder_summary.reminders:
            days_text = f"{reminder.days_until_expiry} 天" if reminder.days_until_expiry is not None else "未知"
            lines.append(f"域名: {reminder.domain}")
            lines.append(f"  剩余天数: {days_text}")
            if reminder.expires_at:
                lines.append(f"  到期时间: {reminder.expires_at}")
            if reminder.days_until_expiry is not None and reminder.days_until_expiry > renewal_days:
                days_to_renew = reminder.days_until_expiry - renewal_days
                lines.append(f"  将在 {days_to_renew} 天后尝试自动续期并部署")
            else:
                lines.append(f"  将在下次定时任务中自动续期并部署")
            lines.append("")
        return "\n".join(lines)

    # ── SMTP 发送 ──

    def _send_email(self, subject: str, body: str) -> None:
        settings = self.config.settings
        host = str(settings["host"])
        port = int(settings["port"]) if settings.get("port") else 465
        sender = str(settings["sender"])
        recipients_raw = settings["recipients"]
        if isinstance(recipients_raw, str):
            recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
        elif isinstance(recipients_raw, list):
            recipients = [str(r).strip() for r in recipients_raw if r]
        else:
            recipients = [str(recipients_raw)]

        username = settings.get("username")
        password = settings.get("password")
        use_ssl = str(settings.get("use_ssl", "true")).lower() in ("true", "1", "yes")

        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        try:
            if use_ssl:
                with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
                    if username and password:
                        smtp.login(str(username), str(password))
                    smtp.sendmail(sender, recipients, msg.as_string())
            else:
                with smtplib.SMTP(host, port, timeout=30) as smtp:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                    if username and password:
                        smtp.login(str(username), str(password))
                    smtp.sendmail(sender, recipients, msg.as_string())
            logger.info("邮件已发送: %s -> %s", subject, recipients)
        except Exception:
            logger.exception("邮件发送失败: %s", subject)
