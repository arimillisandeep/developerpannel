"""Outgoing e-mail. Two ways to send, chosen by what is filled in in backend/.env:

* Gmail API   - GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN (OAuth, scope gmail.send)
* SMTP        - SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD (for Gmail: smtp.gmail.com, 587, an "app password")

Nothing is ever "sent" when neither is set up: configured() is empty and callers must refuse.
Message bodies, passwords and tokens are never written to the log.
"""
import base64
import json
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from app.core.config import settings

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class MailError(Exception):
    """Sending failed. The text is safe to show to an administrator (no secrets in it)."""


def configured() -> str:
    """'gmail_api', 'smtp' or '' (e-mail is not set up)."""
    if settings.GMAIL_REFRESH_TOKEN and settings.GMAIL_CLIENT_ID and settings.GMAIL_CLIENT_SECRET:
        return "gmail_api"
    if settings.SMTP_HOST:
        return "smtp"
    return ""


def sender_address() -> str:
    return (settings.MAIL_FROM or settings.SMTP_USER or "").strip()


def build(to: str, subject: str, text: str, html: str | None = None) -> EmailMessage:
    if "\n" in to or "\r" in to or "@" not in to:
        raise MailError("The recipient address is not valid.")
    msg = EmailMessage()
    sender = sender_address()
    if sender:
        msg["From"] = formataddr((settings.MAIL_FROM_NAME, sender))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = make_msgid(domain=(sender.split("@")[-1] if "@" in sender else "workcode.local"))
    msg["Auto-Submitted"] = "auto-generated"
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _post(url: str, data: bytes, headers: dict) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=settings.MAIL_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        reason = None
        try:
            detail = json.loads(error.read().decode("utf-8", "replace"))
            problem = detail.get("error")
            reason = detail.get("error_description") or (problem.get("message") if isinstance(problem, dict) else problem)
        except Exception:
            pass
        raise MailError(f"Google answered {error.code}: {str(reason or error.reason)[:200]}") from None
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise MailError(f"Google could not be reached: {str(getattr(error, 'reason', error))[:200]}") from None


def _send_gmail_api(msg: EmailMessage):
    form = urllib.parse.urlencode({"client_id": settings.GMAIL_CLIENT_ID, "client_secret": settings.GMAIL_CLIENT_SECRET,
                                   "refresh_token": settings.GMAIL_REFRESH_TOKEN, "grant_type": "refresh_token"}).encode()
    access = _post(GOOGLE_TOKEN_URL, form, {"Content-Type": "application/x-www-form-urlencoded"}).get("access_token")
    if not access:
        raise MailError("Google did not return an access token. Check GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET and GMAIL_REFRESH_TOKEN.")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    sent = _post(GMAIL_SEND_URL, json.dumps({"raw": raw}).encode(),
                 {"Authorization": f"Bearer {access}", "Content-Type": "application/json"})
    if not sent.get("id"):
        raise MailError("Gmail did not accept the message.")


def _send_smtp(msg: EmailMessage):
    if "From" not in msg:
        raise MailError("Set MAIL_FROM (or SMTP_USER) to the sender address.")
    host, port = settings.SMTP_HOST, settings.SMTP_PORT
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=settings.MAIL_TIMEOUT_SECONDS, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=settings.MAIL_TIMEOUT_SECONDS)
        with server:
            server.ehlo()
            if port != 465 and settings.SMTP_STARTTLS:
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            refused = server.send_message(msg)
            if refused:
                raise MailError("The mail server refused the recipient address.")
    except MailError:
        raise
    except smtplib.SMTPAuthenticationError:
        raise MailError("The mail server refused the login. For Gmail use an app password, not the normal password.") from None
    except smtplib.SMTPRecipientsRefused:
        raise MailError("The mail server refused the recipient address.") from None
    except smtplib.SMTPNotSupportedError:
        raise MailError(f"The mail server {host}:{port} does not offer what the settings ask for. "
                        "For Gmail use smtp.gmail.com with port 587 and SMTP_STARTTLS=true "
                        "(or port 465), and an app password as SMTP_PASSWORD.") from None
    except smtplib.SMTPException as error:
        raise MailError(f"The mail server reported an error: {type(error).__name__}") from None
    except (OSError, ssl.SSLError) as error:
        raise MailError(f"The mail server {host}:{port} could not be reached: {type(error).__name__}") from None


def send(to: str, subject: str, text: str, html: str | None = None):
    """Send one message to exactly one address. Raises MailError when it was not handed over."""
    how = configured()
    if not how:
        raise MailError("E-mail is not set up on this server.")
    msg = build(to, subject, text, html)
    if how == "gmail_api":
        _send_gmail_api(msg)
    else:
        _send_smtp(msg)
