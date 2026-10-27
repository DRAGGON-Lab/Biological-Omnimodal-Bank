"""Passwords, sessions, API tokens, and the cross-site write check.

Needs a human security review before any public deployment.
"""

import datetime as dt
import hashlib
import secrets
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from bob.models import ApiToken, User

_hasher = PasswordHasher()
SESSION_USER_KEY = "uid"
SESSION_VERSION_KEY = "sv"
TOKEN_PREFIX = "bob_"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def new_api_token() -> tuple[str, str]:
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, token_digest(token)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def start_session(request: Request, user: User) -> None:
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    request.session[SESSION_VERSION_KEY] = user.session_version


def get_db(request: Request):
    db = request.app.state.sessionmaker()
    try:
        yield db
    finally:
        db.close()


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = _bearer(request)
    if token:
        row = db.scalar(select(ApiToken).where(ApiToken.token_hash == token_digest(token)))
        if row is None:
            raise HTTPException(401, "Invalid API token")
        row.last_used_at = dt.datetime.now(dt.timezone.utc)
        db.commit()
        return db.get(User, row.user_id)
    user_id = request.session.get(SESSION_USER_KEY)
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or request.session.get(SESSION_VERSION_KEY) != user.session_version:
        request.session.clear()
        return None
    return user


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(401, "Not signed in")
    return user


CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
# The docs page starts its viewer with an inline script, which the strict policy forbids.
DOCS_PATHS = ("/docs",)
DOCS_CONTENT_SECURITY_POLICY = CONTENT_SECURITY_POLICY.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'")


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        policy = DOCS_CONTENT_SECURITY_POLICY if request.url.path.startswith(DOCS_PATHS) else CONTENT_SECURITY_POLICY
        response.headers.setdefault("Content-Security-Policy", policy)
        return response


class SameOriginWrites(BaseHTTPMiddleware):
    """Rejects cookie-authenticated writes whose Origin is another site.

    Session cookies are SameSite=Lax, which already stops cross-site form posts; this closes the
    remaining gap for scripted requests. Bearer-token requests carry no ambient credential and
    are exempt.
    """

    async def dispatch(self, request, call_next):
        if request.method in UNSAFE_METHODS and not _bearer(request):
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin:
                host = request.headers.get("host", "")
                allowed_apps = request.app.state.settings.cors_origins
                # Apps allowed by BOB_CORS_ORIGINS sign in for a token; cross-site requests carry no session cookie.
                if urlsplit(origin).netloc != host and origin.rstrip("/") not in allowed_apps:
                    return JSONResponse({"detail": "Cross-site request refused"}, status_code=403)
        return await call_next(request)
