"""Forgot password: request -> e-mail to the account's own address -> single-use link -> new password -> sign in."""
import re
from datetime import timedelta

import pytest

from app.api import auth
from app.core.config import settings
from app.core.security import reset_limiter, reset_token_hash, reset_try_limiter
from app.database import models
from app.database.connection import SessionLocal
from app.services import mailer
from tests.conftest import PASSWORD

NEW = "Fresh#Pass2026"


@pytest.fixture
def logged():
    """Everything written to the log during the test, as one string (via .text)."""
    import io
    import logging
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    old = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)

    class Log:
        @property
        def text(self):
            return stream.getvalue()
    yield Log()
    root.removeHandler(handler)
    root.setLevel(old)


@pytest.fixture
def outbox(monkeypatch):
    """Mail is 'set up' and every message that would leave is collected here instead."""
    sent = []
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(settings, "MAIL_ASYNC", False)
    monkeypatch.setattr(settings, "APP_URL", "http://localhost:5173/")
    monkeypatch.setattr(mailer, "send", lambda to, subject, text, html=None: sent.append({"to": to, "subject": subject, "text": text, "html": html}))
    reset_limiter.reset()
    reset_try_limiter.reset()
    return sent


def token_in(mail) -> str:
    link = re.search(r"http://localhost:5173/reset-password#token=([\w-]+)", mail["text"])
    assert link, mail["text"]
    assert f"#token={link.group(1)}" in mail["html"]
    return link.group(1)


def rows(user_id=None):
    db = SessionLocal()
    try:
        q = db.query(models.PasswordResetToken)
        return [(r.token_hash, r.used_at, r.expires_at) for r in (q.filter_by(user_id=user_id) if user_id else q).order_by(models.PasswordResetToken.id)]
    finally:
        db.close()


def test_not_set_up_is_said_plainly_and_nothing_is_stored(client, org, monkeypatch):
    # This test is about the branch where no mailbox is set up. A developer's own backend/.env may well have a
    # working Gmail/SMTP in it (that is how "Forgot password" is used for real), so the mail settings are emptied
    # for the length of this test instead of assuming the file says nothing.
    for key in ("SMTP_HOST", "GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN"):
        monkeypatch.setattr(settings, key, "")
    assert mailer.configured() == ""
    r = client.post("/api/auth/forgot-password", json={"email": org.intern.user["email"]})
    assert r.status_code == 503 and "not set up" in r.json()["detail"]
    assert rows() == []


def test_full_flow_mail_goes_to_the_account_owner_and_old_password_dies(client, org, outbox, logged):
    intern, email = org.intern, org.intern.user["email"]
    r = client.post("/api/auth/forgot-password", json={"email": f"  {email.upper()} "})
    assert r.status_code == 200 and r.json()["message"] == auth.FORGOT_ANSWER.format(email=org.intern.user["email"])
    assert len(outbox) == 1 and outbox[0]["to"] == email            # only the account's own address, never anyone else
    token = token_in(outbox[0])
    stored = rows(intern.id)
    assert len(stored) == 1 and stored[0][0] == reset_token_hash(token) and stored[0][0] != token   # only the hash is stored
    minutes = (stored[0][2] - models.utcnow()).total_seconds() / 60
    assert 29 < minutes <= 30

    assert client.post("/api/auth/reset-password/validate", json={"token": token}).json()["valid"] is True
    # weak passwords are refused by the server too, and do not use up the link
    for weak in ("short1!", "alllowercase1!", "NoDigits!!", "NoSymbol123"):
        assert client.post("/api/auth/reset-password", json={"token": token, "new_password": weak}).status_code == 422
    r = client.post("/api/auth/reset-password", json={"token": token, "new_password": NEW})
    assert r.status_code == 200 and r.json()["message"] == "Password Reset Successfully"

    assert intern.get("/api/auth/me").status_code == 401             # the session from before the reset is revoked
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401   # old password is dead
    again = client.post("/api/auth/login", json={"email": email, "password": NEW})
    assert again.status_code == 200 and again.json()["user"]["role"] == "intern"
    # single use
    assert client.post("/api/auth/reset-password", json={"token": token, "new_password": "Other#Pass2026"}).status_code == 400
    assert client.post("/api/auth/reset-password/validate", json={"token": token}).status_code == 400
    assert client.post("/api/auth/login", json={"email": email, "password": NEW}).status_code == 200
    # nothing secret in the log, and the database holds a bcrypt hash
    assert token not in logged.text and NEW not in logged.text
    db = SessionLocal()
    user = db.get(models.User, intern.id)
    assert user.password_hash.startswith("$2") and NEW not in user.password_hash
    actions = [a.action for a in db.query(models.AuditLog).filter(models.AuditLog.record_id == str(intern.id)).all()]
    db.close()
    assert {"password.reset_requested", "password.reset_mail_sent", "password.reset"} <= set(actions)


def test_unknown_and_deleted_addresses_are_told_email_not_found_and_get_no_mail(client, org, outbox):
    db = SessionLocal()
    db.get(models.User, org.intern.id).is_active = False
    db.get(models.User, org.dev.id).deleted_at = models.utcnow()
    db.commit()
    db.close()
    for address in ("nobody@wc.test", org.dev.user["email"], "not-an-address"):
        r = client.post("/api/auth/forgot-password", json={"email": address})
        assert r.status_code == 404 and r.json()["detail"] == "Email not found, please enter the correct email."
    r = client.post("/api/auth/forgot-password", json={"email": org.intern.user["email"]})      # switched off by an admin
    assert r.status_code == 403 and "deactivated" in r.json()["detail"]
    assert outbox == [] and rows() == []


def test_a_new_request_cancels_the_link_sent_before(client, org, outbox):
    email = org.dev.user["email"]
    client.post("/api/auth/forgot-password", json={"email": email})
    client.post("/api/auth/forgot-password", json={"email": email})
    first, second = token_in(outbox[0]), token_in(outbox[1])
    assert first != second
    assert client.post("/api/auth/reset-password/validate", json={"token": first}).status_code == 400
    assert client.post("/api/auth/reset-password", json={"token": first, "new_password": NEW}).status_code == 400
    assert client.post("/api/auth/reset-password", json={"token": second, "new_password": NEW}).status_code == 200


def test_expired_and_made_up_links_are_refused(client, org, outbox):
    email = org.intern.user["email"]
    client.post("/api/auth/forgot-password", json={"email": email})
    token = token_in(outbox[0])
    db = SessionLocal()
    db.query(models.PasswordResetToken).update({"expires_at": models.utcnow() - timedelta(seconds=1)})
    db.commit()
    db.close()
    for bad in (token, "x" * 43, token[:-1] + ("A" if token[-1] != "A" else "B")):
        assert client.post("/api/auth/reset-password/validate", json={"token": bad}).status_code == 400
        r = client.post("/api/auth/reset-password", json={"token": bad, "new_password": NEW})
        assert r.status_code == 400 and r.json()["detail"] == auth.BAD_LINK
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200   # password untouched


def test_each_user_gets_only_their_own_mail_and_link(client, org, outbox):
    people = [org.intern, org.dev, org.admin]
    for person in people:
        client.post("/api/auth/forgot-password", json={"email": person.user["email"]})
    assert [m["to"] for m in outbox] == [p.user["email"] for p in people]
    # the intern's link changes the intern's password only
    client.post("/api/auth/reset-password", json={"token": token_in(outbox[0]), "new_password": NEW})
    assert client.post("/api/auth/login", json={"email": org.intern.user["email"], "password": NEW}).status_code == 200
    assert client.post("/api/auth/login", json={"email": org.dev.user["email"], "password": NEW}).status_code == 401
    assert client.post("/api/auth/login", json={"email": org.dev.user["email"], "password": PASSWORD}).status_code == 200


def test_mail_failure_is_said_recorded_and_kills_the_link(client, org, outbox, monkeypatch, logged):
    def broken(to, subject, text, html=None):
        raise mailer.MailError("Google answered 400: Invalid To header")
    monkeypatch.setattr(mailer, "send", broken)
    r = client.post("/api/auth/forgot-password", json={"email": org.intern.user["email"]})
    assert r.status_code == 502 and r.json()["detail"] == auth.MAIL_NOT_SENT and "Invalid To" not in r.text
    stored = rows(org.intern.id)
    assert len(stored) == 1 and stored[0][1] is not None                            # the undelivered link cannot be used
    db = SessionLocal()
    failed = db.query(models.AuditLog).filter_by(action="password.reset_mail_failed").one()
    db.close()
    assert failed.record_id == str(org.intern.id) and "Invalid To header" in str(failed.new_value)
    assert "was not sent" in logged.text and "token=" not in logged.text


def test_too_many_requests_are_slowed_down(client, org, outbox, monkeypatch):
    for _ in range(settings.RESET_RATE_LIMIT):
        assert client.post("/api/auth/forgot-password", json={"email": "someone@wc.test"}).status_code == 404
    assert client.post("/api/auth/forgot-password", json={"email": "someone@wc.test"}).status_code == 429


def test_sign_in_with_employee_code_or_email_and_role_is_returned(client, org):
    code = org.intern.user["employee_code"]
    r = client.post("/api/auth/login", json={"email": code.lower(), "password": PASSWORD})
    assert r.status_code == 200 and r.json()["user"]["id"] == org.intern.id and r.json()["user"]["role"] == "intern"
    assert client.post("/api/auth/login", json={"email": code, "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "WC-E9999", "password": PASSWORD}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "admin@wc.test", "password": PASSWORD}).json()["user"]["role"] == "admin"


def test_smtp_really_talks_to_a_mail_server(monkeypatch):
    """The SMTP path against a real (local) SMTP server: the message arrives for exactly the one recipient."""
    import socket
    import threading
    got = {}

    def serve(sock):
        conn, _ = sock.accept()
        f = conn.makefile("rwb")
        def say(line):
            f.write(line.encode() + b"\r\n"); f.flush()
        say("220 test ESMTP")
        data = None
        while True:
            line = f.readline().decode("utf-8", "replace").rstrip("\r\n")
            if data is not None:
                if line == ".":
                    got["data"] = "\n".join(data); data = None; say("250 queued")
                else:
                    data.append(line)
                continue
            verb = line[:4].upper()
            if verb == "EHLO": say("250 test")
            elif verb == "MAIL": got["from"] = line; say("250 ok")
            elif verb == "RCPT": got.setdefault("rcpt", []).append(line); say("250 ok")
            elif verb == "DATA": data = []; say("354 go")
            elif verb == "QUIT": say("221 bye"); break
            else: say("250 ok")
        conn.close()

    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); sock.listen(1)
    threading.Thread(target=serve, args=(sock,), daemon=True).start()
    for key, value in {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": sock.getsockname()[1], "SMTP_STARTTLS": False, "SMTP_USER": "",
                       "MAIL_FROM": "workcode@wc.test", "GMAIL_REFRESH_TOKEN": ""}.items():
        monkeypatch.setattr(settings, key, value)
    assert mailer.configured() == "smtp"
    mailer.send("kabir@wc.test", *auth.reset_mail("Kabir <b>", "http://localhost:5173/reset-password#token=abc"))
    assert [line.lower() for line in got["rcpt"]] == ["rcpt to:<kabir@wc.test>"] and "workcode@wc.test" in got["from"]
    assert "Subject: Reset your WORKCODE password" in got["data"] and "To: kabir@wc.test" in got["data"]
    assert "Kabir &lt;b&gt;" in got["data"]                      # the name cannot inject HTML into the mail
    with pytest.raises(mailer.MailError):
        mailer.send("bad\naddress@wc.test", "x", "y")
    monkeypatch.setattr(settings, "SMTP_PORT", 1)                # nothing listens there
    with pytest.raises(mailer.MailError, match="could not be reached"):
        mailer.send("kabir@wc.test", "x", "y")


def test_gmail_api_sends_one_raw_message_with_a_fresh_access_token(monkeypatch):
    import base64
    import json
    calls = []

    def fake_post(url, data, headers):
        calls.append((url, data, headers))
        return {"access_token": "ya29.test"} if url == mailer.GOOGLE_TOKEN_URL else {"id": "msg-1"}

    for key, value in {"GMAIL_CLIENT_ID": "cid", "GMAIL_CLIENT_SECRET": "sec", "GMAIL_REFRESH_TOKEN": "rt", "MAIL_FROM": ""}.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(mailer, "_post", fake_post)
    assert mailer.configured() == "gmail_api"
    mailer.send("divya@wc.test", "Reset your WORKCODE password", "body text")
    assert [c[0] for c in calls] == [mailer.GOOGLE_TOKEN_URL, mailer.GMAIL_SEND_URL]
    assert b"grant_type=refresh_token" in calls[0][1] and calls[1][2]["Authorization"] == "Bearer ya29.test"
    raw = base64.urlsafe_b64decode(json.loads(calls[1][1])["raw"]).decode()
    assert "To: divya@wc.test" in raw and "body text" in raw
    monkeypatch.setattr(mailer, "_post", lambda *a: (_ for _ in ()).throw(mailer.MailError("Google answered 401: invalid_grant")))
    with pytest.raises(mailer.MailError, match="invalid_grant"):
        mailer.send("divya@wc.test", "s", "t")
