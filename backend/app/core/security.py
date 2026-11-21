import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: int, role: str, scope: str | None = None, minutes: int | None = None,
                        version: int = 0) -> str:
    """scope=None is a normal login token. A scoped token (e.g. "extension") only works on the endpoints for that scope."""
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "role": role, "iat": now, "ver": version,
               "exp": now + timedelta(minutes=minutes or settings.ACCESS_TOKEN_MINUTES)}
    if scope:
        payload["scope"] = scope
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None


class RateLimiter:
    """Small in-memory sliding-window limiter (per process)."""

    def __init__(self, limit: int, window: int):
        self.limit, self.window = limit, window
        self.hits: dict[str, deque] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True

    def reset(self, key: str | None = None):
        if key is None:
            self.hits.clear()
        else:
            self.hits.pop(key, None)


login_limiter = RateLimiter(settings.LOGIN_RATE_LIMIT, settings.LOGIN_RATE_WINDOW_SECONDS)
reset_limiter = RateLimiter(settings.RESET_RATE_LIMIT, settings.RESET_RATE_WINDOW_SECONDS)     # forgot-password requests
reset_try_limiter = RateLimiter(30, 300)                                                       # reset-link checks per computer


def new_reset_token() -> tuple[str, str]:
    """(token for the e-mail link, hash for the database). Only the hash is ever stored."""
    import hashlib
    import secrets
    token = secrets.token_urlsafe(32)
    return token, hashlib.sha256(token.encode()).hexdigest()


def reset_token_hash(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


def password_problems(password: str) -> list[str]:
    """What a new password still misses (empty list = strong enough). Same rules as the Create New Password page."""
    missing = []
    if len(password) < 8:
        missing.append("at least 8 characters")
    if not any(c.islower() for c in password):
        missing.append("a small letter")
    if not any(c.isupper() for c in password):
        missing.append("a capital letter")
    if not any(c.isdigit() for c in password):
        missing.append("a number")
    if not any(not c.isalnum() for c in password):
        missing.append("a symbol such as @ # ! ?")
    return missing
