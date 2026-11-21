import logging
from datetime import timedelta
from html import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (create_access_token, hash_password, login_limiter, new_reset_token, password_problems,
                               reset_limiter, reset_token_hash, reset_try_limiter, verify_password)
from app.database.connection import SessionLocal, get_db
from app.database.models import DeveloperProfile, EmployeeProfile, PasswordResetToken, User, utcnow
from app.dependencies.auth import client_ip, get_current_user
from app.schemas import ChangePasswordIn, ForgotPasswordIn, LoginIn, ResetPasswordIn, ResetTokenIn
from app.services import mailer
from app.services import timer
from app.services.common import activity, audit, commit
from app.api.users import user_dict

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger("workcode.auth")

FORGOT_ANSWER = "A password reset link has been sent to {email}."
EMAIL_NOT_FOUND = "Email not found, please enter the correct email."
ACCOUNT_OFF = "This account is deactivated. Ask an administrator."
MAIL_NOT_SENT = "The reset e-mail could not be sent. Try again in a few minutes or ask an administrator."
BAD_LINK = "This reset link is not valid or has expired. Request a new one."


def find_login_user(db: Session, identifier: str) -> User | None:
    """The account for what was typed in the sign-in box: the e-mail address, or the employee code (username) such as WC-E0005."""
    identifier = identifier.strip()
    if "@" in identifier:
        return db.query(User).filter(User.email == identifier.lower()).first()
    for profile in (EmployeeProfile, DeveloperProfile):
        row = db.query(profile).filter(func.lower(profile.employee_code) == identifier.lower()).first()
        if row:
            return db.get(User, row.user_id)
    return None


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    email = body.email.strip().lower()
    if not login_limiter.allow(f"{ip}:{email}"):
        raise HTTPException(429, "Too many login attempts. Try again in a few minutes.")
    user = find_login_user(db, email)
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Incorrect email or password")
    if not user.is_active or user.deleted_at is not None:
        raise HTTPException(403, "This account is inactive. Contact an administrator.")
    user.last_login_at = utcnow()
    activity(db, user.id, "login", ip=ip)
    commit(db)
    return {"access_token": create_access_token(user.id, user.role, version=user.token_version or 0), "token_type": "bearer",
            "user": user_dict(db, user, private=True)}


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return user_dict(db, user, private=True)


@router.post("/logout")
def logout(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    s = timer.current(db, user.id)
    if s:
        timer.end(db, s, "logout")
    activity(db, user.id, "logout", ip=client_ip(request), session_id=s.id if s else None)
    user.token_version = (user.token_version or 0) + 1      # the token just used (and any copy of it) is dead from now on
    commit(db)
    return {"ok": True}


@router.post("/change-password")
def change_password(body: ChangePasswordIn, request: Request, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(400, "Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    user.token_version = (user.token_version or 0) + 1      # signs out every other browser that still has an old token
    audit(db, user, "password.change", "users", user.id, ip=client_ip(request))
    commit(db)
    # this browser keeps working: it gets a fresh token for the new version
    return {"ok": True, "access_token": create_access_token(user.id, user.role, version=user.token_version), "token_type": "bearer"}


# ---- forgot password ---------------------------------------------------------------------------------
def reset_mail(name: str, link: str) -> tuple[str, str, str]:
    minutes = settings.PASSWORD_RESET_MINUTES
    subject = "Reset your WORKCODE password"
    text = (f"Hello {name},\n\nA password reset was requested for your WORKCODE account.\n"
            f"Open this link to create a new password (it works once, for {minutes} minutes):\n\n{link}\n\n"
            "If you did not ask for this, ignore this e-mail: your password stays as it is.\n\nWORKCODE")
    html = (f"<div style=\"font-family:Arial,sans-serif;font-size:15px;color:#1b2233;line-height:1.5\">"
            f"<p>Hello {escape(name)},</p><p>A password reset was requested for your WORKCODE account.</p>"
            f"<p><a href=\"{escape(link, quote=True)}\" style=\"display:inline-block;background:#4f6ef7;color:#fff;"
            f"padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:bold\">Create new password</a></p>"
            f"<p>The link works once and for {minutes} minutes. If the button does not open, copy this address into the browser:<br>"
            f"<span style=\"word-break:break-all;color:#4f6ef7\">{escape(link)}</span></p>"
            f"<p style=\"color:#5c6a85\">If you did not ask for this, ignore this e-mail: your password stays as it is.</p></div>")
    return subject, text, html


def deliver_reset_mail(user_id: int, to: str, name: str, link: str, ip: str) -> bool:
    """Hand the link to the mail service. A failure is recorded for the administrators; the link and the token are never logged."""
    try:
        mailer.send(to, *reset_mail(name, link))
        outcome, reason = "password.reset_mail_sent", None
    except mailer.MailError as error:
        outcome, reason = "password.reset_mail_failed", str(error)
        log.warning("password reset e-mail for user %s was not sent: %s", user_id, reason)
    except Exception as error:      # never let a mail problem break the request or leak details
        outcome, reason = "password.reset_mail_failed", type(error).__name__
        log.warning("password reset e-mail for user %s was not sent: %s", user_id, reason)
    db = SessionLocal()
    try:
        if outcome.endswith("failed"):   # the link can never arrive: it must not stay usable
            db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None)) \
                .update({"used_at": utcnow()})
        audit(db, None, outcome, "users", user_id, new={"reason": reason} if reason else None, ip=ip)
        db.commit()
    finally:
        db.close()
    return outcome.endswith("sent")


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordIn, request: Request, db: Session = Depends(get_db)):
    """Send a reset link to the registered address of the account. An address without an account is told so
    (wish of the owner of this installation); the request limit below keeps people from trying long lists of addresses."""
    if not mailer.configured():
        raise HTTPException(503, "Password reset by e-mail is not set up on this server. Ask an administrator to reset your password.")
    ip = client_ip(request)
    email = body.email.strip().lower()
    if not reset_limiter.allow(f"ip:{ip}") or not reset_limiter.allow(f"mail:{email}"):
        raise HTTPException(429, "Too many reset requests. Try again in a few minutes.")
    user = db.query(User).filter(User.email == email).first() if "@" in email else None
    if not user or user.deleted_at is not None:
        raise HTTPException(404, EMAIL_NOT_FOUND)
    if not user.is_active:
        raise HTTPException(403, ACCOUNT_OFF)
    now = utcnow()
    # a new request cancels the links sent before
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)) \
        .update({"used_at": now})
    token, token_hash = new_reset_token()
    db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash, created_at=now, requested_ip=ip,
                              expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_MINUTES)))
    audit(db, None, "password.reset_requested", "users", user.id, ip=ip)
    commit(db)
    # The token travels after "#": browsers never send that part to a server, so it stays out of every access log.
    link = f"{settings.APP_URL.rstrip('/')}/reset-password#token={token}"
    to = user.email                                                 # the address comes from the user's own row, nowhere else
    if not deliver_reset_mail(user.id, to, user.full_name, link, ip):
        raise HTTPException(502, MAIL_NOT_SENT)                     # the reason is in the audit log, not shown to the visitor
    return {"ok": True, "message": FORGOT_ANSWER.format(email=to)}


def usable_reset_token(db: Session, token: str) -> PasswordResetToken | None:
    row = db.query(PasswordResetToken).filter(PasswordResetToken.token_hash == reset_token_hash(token)).first()
    if not row or row.used_at is not None or row.expires_at <= utcnow():
        return None
    user = db.get(User, row.user_id)
    if not user or not user.is_active or user.deleted_at is not None:
        return None
    return row


@router.post("/reset-password/validate")
def validate_reset_token(body: ResetTokenIn, request: Request, db: Session = Depends(get_db)):
    """Lets the Create New Password page tell at once whether the link still works. Nothing is changed."""
    if not reset_try_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    row = usable_reset_token(db, body.token)
    if not row:
        raise HTTPException(400, BAD_LINK)
    return {"valid": True, "expires_in_seconds": max(0, int((row.expires_at - utcnow()).total_seconds()))}


@router.post("/reset-password")
def reset_password(body: ResetPasswordIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    if not reset_try_limiter.allow(ip):
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")
    row = usable_reset_token(db, body.token)
    if not row:
        raise HTTPException(400, BAD_LINK)
    missing = password_problems(body.new_password)
    if missing:
        raise HTTPException(422, "The password needs " + ", ".join(missing) + ".")
    now = utcnow()
    # single use, also when two requests arrive at the same moment: only the one that flips used_at goes on
    claimed = db.query(PasswordResetToken).filter(PasswordResetToken.id == row.id, PasswordResetToken.used_at.is_(None)) \
        .update({"used_at": now})
    if claimed != 1:
        db.rollback()
        raise HTTPException(400, BAD_LINK)
    user = db.get(User, row.user_id)
    user.password_hash = hash_password(body.new_password)
    user.token_version = (user.token_version or 0) + 1          # every browser that was signed in is signed out
    db.query(PasswordResetToken).filter(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)) \
        .update({"used_at": now})
    session = timer.current(db, user.id)
    if session:
        timer.end(db, session, "logout")
    audit(db, user, "password.reset", "users", user.id, ip=ip)
    commit(db)
    login_limiter.reset(f"{ip}:{user.email}")
    return {"ok": True, "message": "Password Reset Successfully"}
