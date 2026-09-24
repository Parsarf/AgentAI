"""Auth flows: signup → verify → login → sessions; reset; adversarial cases."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from itsdangerous import URLSafeTimedSerializer

from core import auth, db
from core.config import settings
from core.logging import register_secret


@pytest.fixture(autouse=True)
def _db_ready(db_pool):
    """Auth touches the database — make sure the pool is open and clean."""
    return db_pool


@pytest.fixture(autouse=True)
def _no_real_email(monkeypatch):
    """Capture outgoing email instead of sending it; expose the links."""
    sent: list[dict] = []

    async def fake_send(to: str, subject: str, html: str) -> None:
        sent.append({"to": to, "subject": subject, "html": html})
        register_secret(html)  # mirrors real redaction behavior for safety

    monkeypatch.setattr(auth, "_send_email", fake_send)
    return sent


def _token_from(sent: list[dict], subject: str) -> str:
    html = next(m["html"] for m in sent if m["subject"] == subject)
    match = re.search(r"token=([A-Za-z0-9_\-]+%2[A-Za-z0-9_\-]+|[A-Za-z0-9_.\-]+)", html)
    assert match, f"no token link in {html}"
    return match.group(1)


async def test_signup_verify_login_roundtrip(_no_real_email):
    user = await auth.signup("carol@example.com", "long enough password 1")
    assert user.status == "email_unverified"

    # Login blocked until verified:
    with pytest.raises(auth.AuthError, match="verify"):
        await auth.login("carol@example.com", "long enough password 1")

    token = _token_from(_no_real_email, "Verify your account")
    verified = await auth.verify_email(token)
    assert verified.status == "active"

    # Verification is single-use:
    with pytest.raises(auth.AuthError, match="already used|expired"):
        await auth.verify_email(token)

    result = await auth.login("carol@example.com", "long enough password 1")
    assert result.user_id == user.id
    assert await auth.verify_session(result.token) == user.id


async def test_forged_and_garbage_tokens_rejected():
    forged = URLSafeTimedSerializer("attacker-secret", salt="auth:verify").dumps(
        {"kind": "verify_email", "uid": str(uuid.uuid4()), "jti": "x"}
    )
    with pytest.raises(auth.AuthError):
        await auth.verify_email(forged)
    with pytest.raises(auth.AuthError):
        await auth.verify_email("not-a-token")


async def test_expired_db_token_rejected(_no_real_email):
    user = await auth.signup("dave@example.com", "long enough password 1")
    jti = uuid.uuid4().hex
    past = datetime.now(UTC) - timedelta(hours=1)
    await db.create_auth_token(user.id, "verify_email", jti, past)
    token = auth._sign({"kind": "verify_email", "uid": str(user.id), "jti": jti}, "verify")
    with pytest.raises(auth.AuthError, match="expired"):
        await auth.verify_email(token)


async def test_wrong_kind_token_rejected(_no_real_email):
    user = await auth.signup("erin@example.com", "long enough password 1")
    jti = uuid.uuid4().hex
    await db.create_auth_token(user.id, "verify_email", jti, datetime.now(UTC) + timedelta(hours=1))
    # Signed with the RESET salt but used against the VERIFY endpoint:
    token = auth._sign({"kind": "password_reset", "uid": str(user.id), "jti": jti}, "reset")
    with pytest.raises(auth.AuthError):
        await auth.verify_email(token)


async def test_password_reset_invalidates_sessions_and_single_use(_no_real_email):
    await auth.signup("frank@example.com", "long enough password 1")
    await auth.verify_email(_token_from(_no_real_email, "Verify your account"))
    first_login = await auth.login("frank@example.com", "long enough password 1")

    await auth.request_password_reset("frank@example.com")
    reset_token = _token_from(_no_real_email, "Reset your password")
    await auth.reset_password(reset_token, "brand new password 99")

    # Old session is dead; old password rejected; new password works:
    assert await auth.verify_session(first_login.token) is None
    with pytest.raises(auth.AuthError, match="Invalid"):
        await auth.login("frank@example.com", "long enough password 1")
    second = await auth.login("frank@example.com", "brand new password 99")
    assert await auth.verify_session(second.token) is not None

    # Reset link cannot be replayed:
    with pytest.raises(auth.AuthError, match="already used|expired"):
        await auth.reset_password(reset_token, "another password 123")


async def test_reset_for_unknown_email_is_silent(_no_real_email):
    before = len(_no_real_email)
    await auth.request_password_reset("nobody-here@example.com")
    assert len(_no_real_email) == before  # no email, no user enumeration


async def test_login_rate_limited(_no_real_email):
    auth._login_attempts.clear()
    with pytest.raises(auth.AuthError):
        for _ in range(auth._LOGIN_MAX_ATTEMPTS + 1):
            await auth.login("greta@example.com", "wrong password xx", ip="10.0.0.9")


async def test_duplicate_signup_rejected(_no_real_email):
    await auth.signup("henry@example.com", "long enough password 1")
    with pytest.raises(auth.AuthError, match="already"):
        await auth.signup("henry@example.com", "another long password")


async def test_short_password_rejected(_no_real_email):
    with pytest.raises(auth.AuthError, match="10 characters"):
        await auth.signup("ivy@example.com", "short")


async def test_missing_session_secret_fails_loudly(monkeypatch):
    from core.config import ConfigError

    monkeypatch.setattr(settings.secrets, "session_secret", None)
    with pytest.raises(ConfigError):
        auth._sign({"kind": "verify_email", "uid": "x", "jti": "y"}, "verify")
