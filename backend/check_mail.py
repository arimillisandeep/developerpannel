"""Check the outgoing e-mail of "Forgot password" without opening the website.

    python check_mail.py                    # only show what is filled in (sends nothing)
    python check_mail.py you@example.com    # send one real test message to that address

It reads backend/.env exactly like the API does, so the answer is the same one
"Forgot password" would get. Secrets are never printed: the password is only
counted, never shown. The text of a failure is the reason the mail server gave,
so it can be fixed without guessing.

Exit codes: 0 = sent, 1 = e-mail is not set up, 2 = the server refused/failed.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from app.core.config import settings          # noqa: E402  (after sys.path)
from app.services import mailer               # noqa: E402

SUBJECT = "WORKCODE test e-mail"
TEXT = ("This is a test message from WORKCODE.\n\n"
        "If you can read this, the reset link of \"Forgot password\" will reach the same inbox.\n"
        "The link inside a real reset mail opens {app}/reset-password\n")
HTML = ("<p>This is a test message from <b>WORKCODE</b>.</p>"
        "<p>If you can read this, the reset link of \"Forgot password\" will reach the same inbox.</p>"
        "<p>The link inside a real reset mail opens {app}/reset-password</p>")


def shown(value: str) -> str:
    """A setting as it may appear on screen: nothing secret, only the shape of it."""
    value = (value or "").strip()
    return "not set" if not value else value


def report() -> str:
    how = mailer.configured()
    app_url = shown(settings.APP_URL)
    lines = [
        "backend/.env",
        f"  way            {how or 'nothing - e-mail is OFF'}",
        f"  APP_URL        {app_url}",
    ]
    if how == "smtp":
        lines += [
            f"  SMTP_HOST      {shown(settings.SMTP_HOST)}",
            f"  SMTP_PORT      {settings.SMTP_PORT}",
            f"  SMTP_STARTTLS  {settings.SMTP_STARTTLS}",
            f"  SMTP_USER      {shown(settings.SMTP_USER)}",
            f"  SMTP_PASSWORD  {('set, ' + str(len(settings.SMTP_PASSWORD.strip())) + ' characters') if settings.SMTP_PASSWORD else 'not set'}",
            f"  MAIL_FROM      {shown(settings.MAIL_FROM or settings.SMTP_USER)}",
        ]
    elif how == "gmail_api":
        lines += [
            f"  GMAIL_CLIENT_ID      {shown(settings.GMAIL_CLIENT_ID)}",
            f"  GMAIL_CLIENT_SECRET  {('set, ' + str(len(settings.GMAIL_CLIENT_SECRET)) + ' characters') if settings.GMAIL_CLIENT_SECRET else 'not set'}",
            f"  GMAIL_REFRESH_TOKEN  {('set, ' + str(len(settings.GMAIL_REFRESH_TOKEN)) + ' characters') if settings.GMAIL_REFRESH_TOKEN else 'not set'}",
            f"  MAIL_FROM            {shown(settings.MAIL_FROM or '(the signed-in Google account)')}",
        ]
    lines.append("  sending        during the request: a failure makes the page answer 502 and is written to the audit log")
    return "\n".join(lines)


def warnings() -> list[str]:
    out = []
    if not mailer.sender_address():
        out.append("MAIL_FROM and SMTP_USER are both empty: the mail server needs a sender address.")
    if settings.SMTP_HOST.lower() == "smtp.gmail.com":
        password = settings.SMTP_PASSWORD.strip()
        if password and len(password) != 16:
            out.append(f"A Gmail app password is 16 characters, this one is {len(password)}. "
                       "Spaces are fine when pasting; anything else is not an app password.")
        if settings.SMTP_PORT not in (465, 587):
            out.append("For smtp.gmail.com use port 587 (STARTTLS) or 465 (SSL).")
    if not settings.APP_URL.rstrip("/").startswith("http"):
        out.append("APP_URL must be the address people open WORKCODE at, e.g. http://localhost:5173")
    return out


def main(argv: list[str]) -> int:
    print(report())
    problems = warnings() if mailer.configured() else []
    for problem in problems:
        print(f"  warning        {problem}")

    if not mailer.configured():
        print("\nE-mail is OFF. \"Forgot password\" answers: \"Password reset by e-mail is not set up on this server.\"")
        print("Fill in SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD and MAIL_FROM in backend/.env, then restart the backend.")
        return 1

    if len(argv) < 2:
        print("\nNothing sent. Give an address to send a real test message to:")
        print("  python check_mail.py you@example.com")
        return 0

    to = argv[1].strip()
    app_url = settings.APP_URL.rstrip("/")
    print(f"\nSending to {to} ...")
    try:
        mailer.send(to, SUBJECT, TEXT.format(app=app_url), HTML.format(app=app_url))
    except mailer.MailError as error:
        print(f"\nNOT SENT: {error}")
        return 2
    print("\nSENT. The mail server accepted the message - check the inbox (and the Spam folder).")
    print("If the inbox stays empty, open the backend log: a real reset mail that failed is logged as")
    print("  password reset e-mail for user <id> was not sent: <reason>")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
