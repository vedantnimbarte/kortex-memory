"""Email delivery.

Two backends, selected by ``KORTEX_EMAIL_BACKEND``:
  - ``log`` (default): logs the message so reset/verify links surface in dev.
  - ``smtp``: sends via SMTP (stdlib ``smtplib`` run in a thread so it doesn't
    block the event loop). Works with any SMTP relay — Postmark, SES SMTP,
    Mailgun, a local MTA. The call sites never change.
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from kortex_core.settings import get_settings
from kortex_core.telemetry.logging import get_logger

log = get_logger("kortex.mailer")


async def send_email(*, to: str, subject: str, body: str) -> None:
    s = get_settings()
    if s.email_backend == "smtp":
        # smtplib is blocking; keep the event loop free.
        await asyncio.to_thread(_send_smtp, s.email_from, to, subject, body)
    else:
        log.info("email_sent", sender=s.email_from, to=to, subject=subject, body=body)


def _send_smtp(sender: str, to: str, subject: str, body: str) -> None:
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as server:
            if s.smtp_starttls:
                server.starttls()
            if s.smtp_user and s.smtp_password is not None:
                server.login(s.smtp_user, s.smtp_password.get_secret_value())
            server.send_message(msg)
        log.info("email_sent", sender=sender, to=to, subject=subject, backend="smtp")
    except Exception as e:
        # Don't let a mail failure break the calling flow (signup/reset still
        # succeed); log loudly so it's visible.
        log.error("email_send_failed", to=to, subject=subject, error=str(e))
