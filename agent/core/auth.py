"""Signup, login, sessions — the front door.

Email + password by default (OAuth login is a later option). Passwords are
argon2id-hashed via passlib. Sessions are opaque random tokens; only their
SHA-256 hash is stored, so a database leak yields no usable session tokens.
Email verification and password reset use HMAC-signed single-purpose links
whose single-use jti is tracked in the auth_tokens table.
"""

from __future__ import annotations

import hashlib
import re
import secrets as secrets_mod
import time
from collections import deque
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext
from pydantic import BaseModel

from core import db
from core.config import ConfigError, settings
from core.logging import get_logger

logger = get_logger(__name__)

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

SESSION_TTL = timedelta(days=30)
VERIFY_TTL = 24 * 3600
RESET_TTL = 30 * 60

_LOGIN_WINDOW = 3600.0
_LOGIN_MAX_ATTEMPTS = 10
_login_attempts: dict[tuple[str, str], deque[float]] = {}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(Exception):
    """Raised for any user-facing auth failure; message is safe to show."""


class LoginResult(BaseModel):
    token: str
    expires_at: datetime
    user_id: UUID


# --------------------------------------------------------------------------- #
# Password + token plumbing
# --------------------------------------------------------------------------- #


def _hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        # Burn comparable time so "no such user" and "wrong password" are not
        # distinguishable by latency.
        pwd_context.dummy_verify()
        return False
    return pwd_context.verify(password, password_hash)


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.require("session_secret"), salt=f"auth:{salt}")


def _sign(payload: dict, salt: str) -> str:
    return _serializer(salt).dumps(payload)


def _unsign(token: str, salt: str, max_age: int) -> dict:
    try:
        payload = _serializer(salt).loads(token, max_age=max_age)
    except SignatureExpired as exc:
        raise AuthError("This link has expired — request a new one.") from exc
    except BadSignature as exc:
        raise AuthError("This link is invalid.") from exc
    if not isinstance(payload, dict) or "uid" not in payload or "jti" not in payload:
        raise AuthError("This link is invalid.")
    return payload


# --------------------------------------------------------------------------- #
# Rate limiting (in-process; production swaps in Redis — noted in BUILD_NOTES)
# --------------------------------------------------------------------------- #


def _rate_limit_ok(email: str, ip: str) -> bool:
    key = (email.lower(), ip)
    now = time.monotonic()
    attempts = _login_attempts.setdefault(key, deque())
    while attempts and now - attempts[0] > _LOGIN_WINDOW:
        attempts.popleft()
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        return False
    attempts.append(now)
    return True


# --------------------------------------------------------------------------- #
# Transactional email (provider-agnostic; unit tests mock this)
# --------------------------------------------------------------------------- #


async def _send_email(to: str, subject: str, html: str) -> None:
    provider = settings.email.provider
    api_key = settings.require("email_api_key")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if provider == "resend":
                resp = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "from": settings.email.from_address,
                        "to": [to],
                        "subject": subject,
                        "html": html,
                    },
                )
            elif provider == "postmark":
                resp = await client.post(
                    "https://api.postmarkapp.com/email",
                    headers={
                        "X-Postmark-Server-Token": api_key,
                        "Accept": "application/json",
                    },
                    json={
                        "From": settings.email.from_address,
                        "To": to,
                        "Subject": subject,
                        "HtmlBody": html,
                    },
                )
            elif provider == "brevo":
                resp = await client.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={"api-key": api_key, "Accept": "application/json"},
                    json={
                        "sender": {"email": settings.email.from_address},
                        "to": [{"email": to}],
                        "subject": subject,
                        "htmlContent": html,
                    },
                )
            else:  # pragma: no cover — guarded by settings validation
                raise ConfigError(f"email.provider: unknown provider {provider!r}")
            resp.raise_for_status()
    except Exception as exc:
        logger.error(
            "email send failed",
            extra={"provider": provider, "to_domain": to.split("@")[-1]},
        )
        raise AuthError(
            f"Could not send email via {provider} — check EMAIL_API_KEY and sender setup."
        ) from exc


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def signup(email: str, password: str) -> db.User:
    """Create an unverified account and email a verification link."""
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        raise AuthError("That doesn't look like a valid email address.")
    if len(password) < 10:
        raise AuthError("Password must be at least 10 characters.")
    if await db.get_user_by_email(email):
        raise AuthError("That email is already registered.")

    user = await db.create_user(
        email, password_hash=_hash_password(password), status="email_unverified"
    )
    jti = uuid4().hex
    expires = datetime.now(UTC) + timedelta(seconds=VERIFY_TTL)
    await db.create_auth_token(user.id, "verify_email", jti, expires)
    token = _sign({"kind": "verify_email", "uid": str(user.id), "jti": jti}, "verify")
    link = f"{settings.secrets.base_url}/verify?token={token}"
    await _send_email(
        to=email,
        subject="Verify your account",
        html=f"<p>Welcome! Confirm your email to activate your agent:</p>"
        f"<p><a href=\"{link}\">Verify my email</a></p>"
        f"<p>This link expires in 24 hours.</p>",
    )
    logger.info("signup created", extra={"user_id": str(user.id)})
    return user


async def verify_email(token: str) -> db.User:
    """Consume a verification link and activate the account. Single-use."""
    payload = _unsign(token, "verify", VERIFY_TTL)
    if payload.get("kind") != "verify_email":
        raise AuthError("This link is invalid.")
    user_id = UUID(payload["uid"])
    if not await db.consume_auth_token(user_id, payload["jti"]):
        raise AuthError("This link was already used or has expired — request a new one.")
    user = await db.update_user(user_id, status="active")
    if user is None:
        raise AuthError("Account no longer exists.")
    logger.info("email verified", extra={"user_id": str(user.id)})
    return user


async def login(email: str, password: str, ip: str = "-") -> LoginResult:
    """Verify credentials and issue an opaque session token.

    Raises the same generic error for unknown users, wrong passwords and
    unverified/suspended accounts.
    """
    email = email.strip().lower()
    if not _rate_limit_ok(email, ip):
        raise AuthError("Too many login attempts — try again in an hour.")

    user = await db.get_user_by_email(email)
    if not _verify_password(password, user.password_hash if user else None):
        raise AuthError("Invalid email or password.")
    assert user is not None
    if user.status == "email_unverified":
        raise AuthError("Please verify your email before logging in.")
    if user.status != "active":
        raise AuthError("Invalid email or password.")

    raw_token = secrets_mod.token_urlsafe(32)
    expires_at = datetime.now(UTC) + SESSION_TTL
    session = await db.create_session(user.id, _token_hash(raw_token), expires_at)
    logger.info("login ok", extra={"user_id": str(user.id), "session_id": str(session.id)})
    return LoginResult(token=raw_token, expires_at=expires_at, user_id=user.id)


async def verify_session(token: str) -> UUID | None:
    """Resolve a session token to its user_id, or None if invalid/expired."""
    resolved = await db.get_session_by_token_hash(_token_hash(token))
    if resolved is None:
        return None
    session, user = resolved
    if user.status != "active":
        return None
    return user.id


async def logout(token: str) -> None:
    await db.delete_session(_token_hash(token))


async def request_password_reset(email: str) -> None:
    """Email a reset link if the account exists. Always silent about misses."""
    email = email.strip().lower()
    user = await db.get_user_by_email(email)
    if user is None or not user.password_hash:
        return
    jti = uuid4().hex
    expires = datetime.now(UTC) + timedelta(seconds=RESET_TTL)
    await db.create_auth_token(user.id, "password_reset", jti, expires)
    token = _sign({"kind": "password_reset", "uid": str(user.id), "jti": jti}, "reset")
    link = f"{settings.secrets.base_url}/reset?token={token}"
    await _send_email(
        to=email,
        subject="Reset your password",
        html=f"<p>Reset your password:</p>"
        f"<p><a href=\"{link}\">Choose a new password</a></p>"
        f"<p>This link works once and expires in 30 minutes. "
        f"If you didn't ask for this, ignore this email.</p>",
    )
    logger.info("password reset requested", extra={"user_id": str(user.id)})


async def reset_password(token: str, new_password: str) -> None:
    """Consume a reset link, set the new password, kill all existing sessions."""
    if len(new_password) < 10:
        raise AuthError("Password must be at least 10 characters.")
    payload = _unsign(token, "reset", RESET_TTL)
    if payload.get("kind") != "password_reset":
        raise AuthError("This link is invalid.")
    user_id = UUID(payload["uid"])
    if not await db.consume_auth_token(user_id, payload["jti"]):
        raise AuthError("This link was already used or has expired — request a new one.")
    await db.update_user(user_id, password_hash=_hash_password(new_password))
    await db.delete_sessions_for_user(user_id)
    logger.info("password reset done", extra={"user_id": str(user_id)})
