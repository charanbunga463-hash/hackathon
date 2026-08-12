"""Outbound email.

No provider existed in this project, so this is a small abstraction over SMTP —
which every provider (SES, SendGrid, Postmark, Mailgun, Gmail) speaks — rather
than a hard dependency on one vendor's SDK. Configuration is entirely
environment-driven; nothing here is hardcoded.

Two transports:

  * `SmtpEmailSender`    — the real one. Used whenever SMTP_HOST is set.
  * `ConsoleEmailSender` — writes the message to the log instead of sending.
                           Development only: `validate_for_environment()`
                           refuses to start a production instance that has
                           accounts enabled and no SMTP host, so this cannot
                           be what a deployed instance silently falls back to.

Sending is blocking socket work, so it runs on the IO pool rather than the
event loop. Delivery failures raise `EmailError`; callers decide whether that
should fail the request.
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from ..config.settings import Settings
from ..runtime.concurrency import io_bound
from ..utils.logging import get_logger

logger = get_logger(__name__)


class EmailError(RuntimeError):
    pass


class EmailSender(Protocol):
    name: str

    def send(self, *, to: str, subject: str, text: str, html: str | None = None) -> None: ...


class ConsoleEmailSender:
    """Development transport: logs the message instead of sending it."""

    name = "console"

    def send(self, *, to: str, subject: str, text: str, html: str | None = None) -> None:
        logger.warning(
            "EMAIL NOT SENT (no SMTP_HOST configured) — development transport.\n"
            "  to      : %s\n  subject : %s\n%s",
            to,
            subject,
            "\n".join(f"  | {line}" for line in text.splitlines()),
        )


class SmtpEmailSender:
    name = "smtp"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, *, to: str, subject: str, text: str, html: str | None = None) -> None:
        settings = self.settings
        message = EmailMessage()
        message["From"] = settings.smtp_from_email or settings.smtp_username or "no-reply@localhost"
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        if html:
            message.add_alternative(html, subtype="html")

        try:
            if settings.smtp_use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    settings.smtp_host, settings.smtp_port,
                    timeout=settings.smtp_timeout_seconds, context=context,
                ) as server:
                    self._authenticate(server)
                    server.send_message(message)
            else:
                with smtplib.SMTP(
                    settings.smtp_host, settings.smtp_port,
                    timeout=settings.smtp_timeout_seconds,
                ) as server:
                    if settings.smtp_use_tls:
                        server.starttls(context=ssl.create_default_context())
                    self._authenticate(server)
                    server.send_message(message)
        except Exception as exc:
            # The exception text can contain the recipient and server banner but
            # never the password; still, callers must not forward it to a client.
            raise EmailError(f"{type(exc).__name__}: {exc}") from exc

    def _authenticate(self, server: smtplib.SMTP) -> None:
        if self.settings.smtp_username:
            server.login(self.settings.smtp_username, self.settings.smtp_password or "")


class EmailService:
    def __init__(self, settings: Settings, sender: EmailSender | None = None) -> None:
        self.settings = settings
        self.sender: EmailSender = sender or (
            SmtpEmailSender(settings) if settings.smtp_host else ConsoleEmailSender()
        )

    @property
    def transport(self) -> str:
        return self.sender.name

    async def send_otp(self, *, to: str, code: str, purpose: str) -> None:
        minutes = max(1, self.settings.otp_ttl_seconds // 60)
        heading = (
            "Verify your email" if purpose == "verify" else "Reset your password"
        )
        text = (
            f"{self.settings.app_name}\n\n"
            f"{heading}\n\n"
            f"Your verification code is:\n\n"
            f"    {code}\n\n"
            f"This code expires in {minutes} minutes.\n\n"
            f"If you did not request this code, you can ignore this email.\n"
        )
        html = _otp_html(self.settings.app_name, heading, code, minutes)
        await io_bound(
            self.sender.send,
            to=to,
            subject=f"{self.settings.app_name} verification code: {code}",
            text=text,
            html=html,
        )

    async def send_password_changed(self, *, to: str) -> None:
        text = (
            f"{self.settings.app_name}\n\n"
            "Your password was just changed, and you have been signed out on every "
            "device.\n\nIf this was not you, reset your password immediately.\n"
        )
        await io_bound(
            self.sender.send,
            to=to,
            subject=f"{self.settings.app_name}: your password was changed",
            text=text,
        )


def _otp_html(app_name: str, heading: str, code: str, minutes: int) -> str:
    return f"""\
<!doctype html>
<html><body style="margin:0;padding:24px;background:#0b0d10;font-family:system-ui,-apple-system,Segoe UI,sans-serif;color:#e6e9ef">
  <div style="max-width:460px;margin:0 auto;background:#12151a;border:1px solid #232936;border-radius:12px;padding:28px">
    <p style="margin:0 0 20px;font-size:15px;font-weight:600;letter-spacing:-0.01em">{app_name}</p>
    <p style="margin:0 0 8px;font-size:18px;font-weight:600">{heading}</p>
    <p style="margin:0 0 20px;font-size:13px;color:#9aa4b2">Your verification code is:</p>
    <p style="margin:0 0 20px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:30px;font-weight:600;letter-spacing:8px;color:#5b9cff">{code}</p>
    <p style="margin:0 0 6px;font-size:12px;color:#9aa4b2">This code expires in {minutes} minutes.</p>
    <p style="margin:0;font-size:12px;color:#6b7482">If you did not request this code, you can ignore this email.</p>
  </div>
</body></html>"""


_service: EmailService | None = None


def get_email_service(settings: Settings) -> EmailService:
    global _service
    if _service is None:
        _service = EmailService(settings)
    return _service


def reset_email_service() -> None:
    global _service
    _service = None
