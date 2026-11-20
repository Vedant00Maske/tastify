"""Outgoing e-mail (Milestone 7, ADR-020).

The API never talks to the mail server itself: `CeleryMailer` queues a message and the worker
delivers it over SMTP, retrying with backoff while the server is unavailable (spec §4,
retry-safe asynchronous processing). Deployments without a worker (Vercel) set
MAIL_DELIVERY=inline: `InlineMailer` sends from the API, without retries. Without SMTP_HOST,
`DisabledMailer` refuses, and the features that need e-mail say so instead of pretending to work.
"""

import asyncio
import logging
import smtplib
import ssl
from dataclasses import asdict, dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Protocol

from app.core import metrics
from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    kind: str  # password_reset | email_verification (metrics and logs; never the content)


class MailUnavailableError(RuntimeError):
    """E-mail is not configured, or the message could not be queued."""


class Mailer(Protocol):
    async def send(self, email: Email) -> None: ...


class DisabledMailer:
    async def send(self, email: Email) -> None:
        metrics.EMAILS.labels(email.kind, "disabled").inc()
        raise MailUnavailableError("e-mail is not configured (SMTP_HOST)")


class CeleryMailer:
    async def send(self, email: Email) -> None:
        from app.workers.tasks import send_email

        try:
            await asyncio.to_thread(send_email.delay, asdict(email))
        except Exception as error:  # broker unreachable
            metrics.EMAILS.labels(email.kind, "queue_failed").inc()
            logger.exception("Could not queue %s e-mail", email.kind)
            raise MailUnavailableError("e-mail could not be queued") from error
        metrics.EMAILS.labels(email.kind, "queued").inc()


class InlineMailer:
    """Sends over SMTP inside the API process (MAIL_DELIVERY=inline), for deployments without a
    Celery worker. A failure is not retried: the user asks for a new link."""

    async def send(self, email: Email) -> None:
        try:
            await asyncio.to_thread(deliver, email)
        except (smtplib.SMTPException, OSError) as error:
            metrics.EMAILS.labels(email.kind, "failed").inc()
            logger.warning("%s e-mail not delivered: %s", email.kind, type(error).__name__)
            raise MailUnavailableError("e-mail could not be sent") from error
        metrics.EMAILS.labels(email.kind, "sent").inc()
        logger.info("%s e-mail delivered", email.kind)


def get_mailer() -> Mailer:
    """FastAPI dependency (tests override it with a recording mailer)."""
    settings = get_settings()
    if not settings.mail_enabled:
        return DisabledMailer()
    return InlineMailer() if settings.mail_delivery == "inline" else CeleryMailer()


def build_message(email: Email, settings: Settings) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = email.to
    message["Subject"] = email.subject
    message["Message-ID"] = make_msgid(domain=settings.mail_from.rsplit("@", 1)[-1].strip("> "))
    # Links carry single-use secrets: ask clients not to auto-forward or track.
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(email.text)
    return message


def deliver(email: Email, settings: Settings | None = None) -> None:
    """Send one message over SMTP (runs in the worker; raises on failure so it is retried)."""
    settings = settings or get_settings()
    if not settings.smtp_host:
        raise MailUnavailableError("SMTP_HOST is not set")
    message = build_message(email, settings)
    context = ssl.create_default_context()
    smtp: smtplib.SMTP
    if settings.smtp_security == "tls":
        smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30, context=context)
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    with smtp:
        if settings.smtp_security == "starttls":
            smtp.starttls(context=context)
        if settings.smtp_username and settings.smtp_password:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
