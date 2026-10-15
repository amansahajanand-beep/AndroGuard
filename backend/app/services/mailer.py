from __future__ import annotations

import html as html_lib
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger(__name__)


def mail_configured() -> bool:
    return bool((settings.smtp_host or "").strip() and (settings.smtp_from or "").strip())


def send_email(to: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    """Send via SMTP. Returns False (and logs) when unconfigured or on failure."""
    if not mail_configured():
        logger.warning("SMTP is not configured (SMTP_HOST / SMTP_FROM); email not sent")
        return False
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    try:
        if settings.smtp_use_ssl:
            server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
        with server:
            if not settings.smtp_use_ssl and settings.smtp_use_tls:
                server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password or "")
            refused = server.send_message(msg)
        masked = to[:2] + "***@" + to.split("@")[-1] if "@" in to else "***"
        logger.info("Email accepted by %s for %s (subject=%r, refused=%s)", settings.smtp_host, masked, subject, refused or {})
        return True
    except Exception:
        logger.exception("Failed to send email")
        return False


def send_password_reset_email(to: str, full_name: str, reset_url: str) -> bool:
    minutes = settings.password_reset_expire_minutes
    safe_name = html_lib.escape(full_name)
    text = (
        f"Hi {full_name},\n\n"
        f"We received a request to reset your password. Use the link below "
        f"(valid for {minutes} minutes):\n\n{reset_url}\n\n"
        "If you didn't request this, you can ignore this email."
    )
    html = (
        f"<p>Hi {safe_name},</p>"
        f"<p>We received a request to reset your password. "
        f'<a href="{reset_url}">Reset your password</a> (valid for {minutes} minutes).</p>'
        "<p>If you didn't request this, you can ignore this email.</p>"
    )
    return send_email(to, "Reset your password", text, html)
