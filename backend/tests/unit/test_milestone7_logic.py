"""Milestone 7 logic without services: log redaction and format, request ids, token key
rotation, e-mail construction and delivery."""

import base64
import json
import logging
import os
import smtplib
import uuid
from typing import Any, ClassVar, Literal

import pytest

from app.core import mail
from app.core.config import Settings
from app.core.logging import ContextFilter, JsonFormatter, redact
from app.core.request_context import new_request_id, request_id_var
from app.domains.auth.recovery import reset_email, verification_email
from app.domains.integrations.tokens import TokenCipher, TokenDecryptionError


@pytest.mark.parametrize(
    ("raw", "secret"),
    [
        ("GET /callback?code=abc123&state=xyz789", "abc123"),
        ("GET /callback?code=abc123&state=xyz789", "xyz789"),
        ("Authorization: Bearer sk-live-123.456", "sk-live-123.456"),
        ('{"password": "hunter2 hunter2"}', "hunter2"),
        ('{"new_password":"p4ss word"}', "p4ss word"),
        ("cookie soniqueo_session=Zm9vYmFy; path=/", "Zm9vYmFy"),
        ("refresh_token=rt-1&x=1", "rt-1"),
    ],
)
def test_secrets_are_redacted(raw: str, secret: str) -> None:
    assert secret not in redact(raw)
    assert "[redacted]" in redact(raw)


def test_ordinary_messages_are_untouched() -> None:
    text = "user registered user=7d9e and played 3 tracks"
    assert redact(text) == text


def test_json_logs_carry_the_request_id_and_extra_fields() -> None:
    token = request_id_var.set("req-12345678")
    try:
        record = logging.LogRecord(
            "t", logging.INFO, __file__, 1, "login code=%s", ("s3cr3t",), None
        )
        record.route = "/auth/login"
        ContextFilter().filter(record)
        entry = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)
    assert entry["request_id"] == "req-12345678"
    assert entry["route"] == "/auth/login"
    assert "s3cr3t" not in entry["message"]
    assert entry["level"] == "INFO"


@pytest.mark.parametrize(
    ("incoming", "kept"),
    [
        ("abcdef12-3456", True),
        ("short", False),
        ("x" * 65, False),
        ("has space inside", False),
        ("new\nline-12345", False),
        (None, False),
    ],
)
def test_request_ids_are_kept_only_when_plain(incoming: str | None, kept: bool) -> None:
    result = new_request_id(incoming)
    assert (result == incoming) is kept
    assert len(result) >= 8


def _key() -> bytes:
    return os.urandom(32)


def test_token_key_rotation_reads_old_values_and_writes_new_ones() -> None:
    user, provider = uuid.uuid4(), "spotify"
    old_key, new_key = _key(), _key()
    old_value = TokenCipher(old_key).encrypt("access-token", user, provider)

    rotating = TokenCipher(new_key, [old_key])
    assert rotating.decrypt(old_value, user, provider) == "access-token"
    assert not rotating.is_current(old_value, user, provider)
    new_value = rotating.encrypt("access-token", user, provider)
    assert rotating.is_current(new_value, user, provider)

    with pytest.raises(TokenDecryptionError):
        TokenCipher(new_key).decrypt(old_value, user, provider)  # old key removed too early
    assert TokenCipher(new_key).decrypt(new_value, user, provider) == "access-token"
    with pytest.raises(TokenDecryptionError):
        rotating.decrypt(new_value, uuid.uuid4(), provider)  # still bound to its user


def test_previous_keys_come_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.domains.integrations import tokens

    old, new = _key(), _key()
    settings = Settings(
        _env_file=None,
        integrations_token_key=base64.b64encode(new).decode(),
        integrations_token_previous_keys=[base64.b64encode(old).decode()],
    )
    monkeypatch.setattr(tokens, "get_settings", lambda: settings)
    user = uuid.uuid4()
    value = TokenCipher(old).encrypt("t", user, "youtube")
    assert TokenCipher.from_settings().decrypt(value, user, "youtube") == "t"


def test_recovery_emails_link_to_the_public_app() -> None:
    reset = reset_email("a@example.com", "TOKEN123", 60)
    assert "/reset-password?token=TOKEN123" in reset.text
    assert "60 minutes" in reset.text
    verify = verification_email("a@example.com", "TOKEN456", 48)
    assert "/verify-email?token=TOKEN456" in verify.text
    assert verify.kind == "email_verification"


class FakeSMTP:
    instances: ClassVar[list["FakeSMTP"]] = []

    def __init__(self, host: str, port: int, timeout: int, **_: Any) -> None:
        self.host, self.port = host, port
        self.calls: list[str] = []
        self.sent: list[Any] = []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_: object) -> None:
        self.calls.append("quit")

    def starttls(self, context: Any) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login:{user}")

    def send_message(self, message: Any) -> None:
        self.sent.append(message)


def test_delivery_uses_starttls_and_login(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    settings = Settings(
        _env_file=None,
        smtp_host="smtp.example",
        smtp_port=587,
        smtp_username="mailer",
        smtp_password="pw",  # noqa: S106 - test value
        mail_from="SONIQUEO <no-reply@soniqueo.example>",
    )
    mail.deliver(reset_email("person@example.com", "TOK", 60), settings)
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.example", 587)
    assert smtp.calls[:2] == ["starttls", "login:mailer"]
    message = smtp.sent[0]
    assert message["To"] == "person@example.com"
    assert message["From"] == "SONIQUEO <no-reply@soniqueo.example>"
    assert message["Message-ID"].endswith("@soniqueo.example>")


def test_delivery_without_smtp_is_refused() -> None:
    with pytest.raises(mail.MailUnavailableError):
        mail.deliver(reset_email("p@example.com", "T", 60), Settings(_env_file=None))


async def test_disabled_mailer_refuses() -> None:
    with pytest.raises(mail.MailUnavailableError):
        await mail.DisabledMailer().send(reset_email("p@example.com", "T", 60))


@pytest.mark.parametrize(
    ("smtp_host", "delivery", "expected"),
    [
        (None, "inline", mail.DisabledMailer),
        ("smtp.example", "queue", mail.CeleryMailer),
        ("smtp.example", "inline", mail.InlineMailer),
    ],
)
def test_mailer_follows_the_delivery_setting(
    monkeypatch: pytest.MonkeyPatch,
    smtp_host: str | None,
    delivery: Literal["queue", "inline"],
    expected: type,
) -> None:
    settings = Settings(_env_file=None, smtp_host=smtp_host, mail_delivery=delivery)
    monkeypatch.setattr(mail, "get_settings", lambda: settings)
    assert isinstance(mail.get_mailer(), expected)


async def test_inline_mailer_sends_and_reports_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSMTP.instances.clear()
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    settings = Settings(_env_file=None, smtp_host="smtp.example", mail_delivery="inline")
    monkeypatch.setattr(mail, "get_settings", lambda: settings)

    await mail.InlineMailer().send(reset_email("person@example.com", "TOK", 60))
    assert FakeSMTP.instances[0].sent[0]["To"] == "person@example.com"

    def refuse(*_: Any, **__: Any) -> None:
        raise smtplib.SMTPServerDisconnected("gone")

    monkeypatch.setattr(smtplib, "SMTP", refuse)
    with pytest.raises(mail.MailUnavailableError):
        await mail.InlineMailer().send(reset_email("person@example.com", "TOK", 60))


def test_backup_age_metric_reads_the_status_file(tmp_path: Any) -> None:
    from app.core.metrics import BackupStatusCollector

    status = tmp_path / "last_success"
    collector = BackupStatusCollector(str(status))
    missing = next(iter(collector.collect()))
    assert missing.samples[0].value == 0.0  # no backup yet: the alert fires
    status.write_text("1795100000\n")
    present = next(iter(collector.collect()))
    assert present.name == "soniqueo_backup_last_success_timestamp_seconds"
    assert present.samples[0].value == 1795100000.0
