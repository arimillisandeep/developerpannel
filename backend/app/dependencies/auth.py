from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

import logging

from app.core import permissions as P
from app.core.config import settings
from app.core.security import decode_token
from app.database.connection import get_db
from app.database.models import User

bearer = HTTPBearer(auto_error=False)
log = logging.getLogger("workcode.auth")


def user_from_token(db: Session, token: str | None, scope: str | None = None) -> User | None:
    payload = decode_token(token) if token else None
    if not payload or payload.get("scope") != scope:   # a browser-extension token cannot be used as a login token
        return None
    user = db.get(User, int(payload["sub"]))
    if not user or not user.is_active or user.deleted_at is not None:
        return None
    # Login tokens carry the user's token version. Logout, a password change and an admin password reset raise it,
    # so every older login token stops working at once. (Extension tokens can only report a site category; they stay.)
    if scope is None and int(payload.get("ver", 0)) != (user.token_version or 0):
        return None
    return user


def get_current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                     x_workcode_token: str | None = Header(None),
                     db: Session = Depends(get_db)) -> User:
    # Some reverse proxies strip or replace the Authorization header, so the same JWT is
    # also accepted in X-Workcode-Token. It is validated identically.
    user = user_from_token(db, creds.credentials if creds else None) or user_from_token(db, x_workcode_token)
    if not user and settings.ALLOW_QUERY_TOKEN:
        # Hosted previews whose proxy drops request headers. Off by default: tokens in URLs end up in logs.
        user = user_from_token(db, request.query_params.get("_t"))
    if not user:
        log.info("401 %s  authorization: %s, x-workcode-token: %s, query token: %s, referer: %s",
                 request.url.path, "authorization" in request.headers, "x-workcode-token" in request.headers,
                 "_t" in request.query_params, request.headers.get("referer"))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated",
                            headers={"WWW-Authenticate": "Bearer"})
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission for this action")
        return user
    return dep


admin_only = require_roles(P.ADMIN)          # the usual guard for the admin screens


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
