"""Outgoing e-mail: what happens in backend/.env decides whether it works, and every failure says why."""
import smtplib

import pytest

from app.core.config import settings
from app.services import mailer


@pytest.fixture(autouse=True)
def clean_mail_settings(monkeypatch):
    """E-mail off, nothing set - each test turns on only what it needs."""
    for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM",
                 "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_STARTTLS", True)
    monkeypatch.setattr(settings, "MAIL_FROM_NAME", "WORKCODE")


def smtp_on(monkeypatch, host="smtp.gmail.com"):
    monkeypatch.setattr(settings, "SMTP_HOST", host)
    monkeypatch.setattr(settings, "SMTP_USER", "sender@gmail.com")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "abcdefghijklmnop")
    monkeypatch.setattr(settings, "MAIL_FROM", "sender@gmail.com")


class ExplodingSMTP:
    """Stands in for smtplib.SMTP: connects, then fails at the step the test wants to see."""

    def __init__(self, error=None, **kwargs):
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def ehlo(self):
        return 250, b"ok"

    def starttls(self, context=None):
        if self.error == "no_starttls":
            raise smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server.")

    def login(self, user, password):
        if self.error == "bad_login":
            raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Username and Password not accepted")

    def send_message(self, msg):
        if self.error == "no_starttls":
            raise smtplib.SMTPNotSupportedError("AUTH extension not supported by server.")
        return {}


def test_nothing_set_up_means_nothing_is_sent():
    assert mailer.configured() == ""
    with pytest.raises(mailer.MailError) as error:
        mailer.send("someone@example.com", "s", "t")
    assert str(error.value) == "E-mail is not set up on this server."


def test_gmail_api_wins_when_all_three_are_set(monkeypatch):
    smtp_on(monkeypatch)
    monkeypatch.setattr(settings, "GMAIL_CLIENT_ID", "id")
    monkeypatch.setattr(settings, "GMAIL_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "GMAIL_REFRESH_TOKEN", "refresh")
    assert mailer.configured() == "gmail_api"


def test_smtp_is_used_when_only_smtp_is_set(monkeypatch):
    smtp_on(monkeypatch)
    assert mailer.configured() == "smtp"


def test_sender_defaults_to_smtp_user(monkeypatch):
    smtp_on(monkeypatch)
    monkeypatch.setattr(settings, "MAIL_FROM", "")
    assert mailer.sender_address() == "sender@gmail.com"


def test_bad_recipient_is_refused_before_anything_leaves(monkeypatch):
    smtp_on(monkeypatch)
    for bad in ("", "no-at-sign", "two@lines\n@example.com"):
        with pytest.raises(mailer.MailError):
            mailer.build(bad, "s", "t")


def test_send_hands_the_message_over(monkeypatch):
    smtp_on(monkeypatch)
    sent = []
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: ExplodingSMTP(**k))
    monkeypatch.setattr(ExplodingSMTP, "send_message", lambda self, msg: sent.append(msg) or {})
    mailer.send("intern@workcode.local", "Reset your WORKCODE password", "hello")
    assert len(sent) == 1
    assert sent[0]["To"] == "intern@workcode.local"
    assert "From" in sent[0]


def test_wrong_app_password_says_so(monkeypatch):
    smtp_on(monkeypatch)
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: ExplodingSMTP(error="bad_login", **k))
    with pytest.raises(mailer.MailError) as error:
        mailer.send("intern@workcode.local", "s", "t")
    assert "app password" in str(error.value)


def test_mail_server_without_starttls_names_the_setting(monkeypatch):
    smtp_on(monkeypatch, host="127.0.0.1")
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: ExplodingSMTP(error="no_starttls", **k))
    with pytest.raises(mailer.MailError) as error:
        mailer.send("intern@workcode.local", "s", "t")
    assert "SMTP_STARTTLS" in str(error.value)


def test_password_is_never_in_the_error(monkeypatch):
    smtp_on(monkeypatch)
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: ExplodingSMTP(error="bad_login", **k))
    with pytest.raises(mailer.MailError) as error:
        mailer.send("intern@workcode.local", "s", "t")
    assert settings.SMTP_PASSWORD not in str(error.value)
