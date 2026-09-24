"""Postgres access layer — tenant-scoped by construction.

Every function that touches a tenant table takes ``user_id`` as its required
first argument and includes it in the WHERE clause. There is no code path
that queries a tenant table without it. The ONE deliberate exception is
:func:`due_jobs`, documented on the function itself.

Money is Decimal/NUMERIC end to end. Access goes through this module only —
callers never write SQL.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg
from pgvector import Vector
from pgvector.asyncpg import register_vector
from pydantic import BaseModel, ConfigDict

from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "db" / "migrations"

_pool: asyncpg.Pool | None = None
_pool_dsn: str | None = None


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #


class _Row(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class User(_Row):
    id: UUID
    email: str
    password_hash: str | None = None
    oauth_subject: str | None = None
    created_at: datetime
    plan_tier: str
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    billing_state: str = "none"
    billing_grace_until: datetime | None = None
    status: str
    timezone: str = "UTC"
    user_limits_json: dict | None = None
    settings_json: dict = {}


class SessionInfo(_Row):
    id: UUID
    user_id: UUID
    token_hash: str
    expires_at: datetime
    created_at: datetime


class Task(_Row):
    id: UUID
    user_id: UUID
    request: str
    status: str
    source: str
    parent_job_id: UUID | None = None
    steps_json: Any = []
    result: str | None = None
    cost_usd: Decimal = Decimal("0")
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Memory(_Row):
    id: UUID
    user_id: UUID
    content: str
    category: str
    embedding: list[float] | None = None
    importance: float = 0.5
    created_at: datetime
    last_used_at: datetime | None = None
    distance: float | None = None  # only set by search_memories()


class Job(_Row):
    id: UUID
    user_id: UUID
    kind: str
    schedule: str
    check_mode: str
    check_script_path: str | None = None
    instruction: str
    state_json: Any = {}
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    active: bool = True
    created_by_task: UUID | None = None
    created_at: datetime


class Approval(_Row):
    id: UUID
    user_id: UUID
    task_id: UUID | None = None
    action_summary: str
    details_json: Any = {}
    status: str
    created_at: datetime
    decided_at: datetime | None = None


class SpendEntry(_Row):
    id: UUID
    user_id: UUID
    merchant: str
    amount: Decimal
    currency: str
    approved_by: str
    status: str
    task_id: UUID | None = None
    created_at: datetime


class SkillMeta(_Row):
    id: UUID
    user_id: UUID
    name: str
    created_at: datetime
    uses: int
    successes: int
    failures: int
    reviewed: bool
    last_used_at: datetime | None = None


class UsagePeriod(_Row):
    id: UUID
    user_id: UUID
    period_start: date
    period_end: date
    total_cost: Decimal
    included_allowance: Decimal
    overage: Decimal
    updated_at: datetime


class UsageSummary(_Row):
    period_start: date
    period_end: date
    total_cost: Decimal
    included_allowance: Decimal
    overage: Decimal
    plan_tier: str


class VaultEntry(_Row):
    id: UUID
    user_id: UUID
    site: str
    encrypted_blob: bytes
    created_at: datetime
    updated_at: datetime


def _user(row: asyncpg.Record) -> User:
    return User(**dict(row))


def _embedding(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [float(x) for x in value]
    if hasattr(value, "to_list"):  # pgvector Vector
        return [float(x) for x in value.to_list()]
    if hasattr(value, "tolist"):  # numpy array
        return [float(x) for x in value.tolist()]
    return [float(x) for x in value]


# --------------------------------------------------------------------------- #
# Pool / migrations
# --------------------------------------------------------------------------- #


async def apply_migrations(dsn: str | None = None) -> list[int]:
    """Apply pending numbered migrations in order, each exactly once."""
    dsn = dsn or settings.secrets.database_url
    conn = await asyncpg.connect(dsn)
    applied: list[int] = []
    try:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations("
            "version integer PRIMARY KEY, "
            "applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(path.name.split("_", 1)[0])
            if version in done:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text())
                await conn.execute("INSERT INTO schema_migrations(version) VALUES ($1)", version)
            applied.append(version)
            logger.info("migration applied", extra={"migration": path.name})
    finally:
        await conn.close()
    return applied


async def open_pool(dsn: str | None = None, force: bool = False) -> None:
    """Open the connection pool sized for concurrent multi-user load.

    force=True rebinds even when a pool with the same DSN exists — tests need
    this because a pool is bound to the loop that created it.
    """
    global _pool, _pool_dsn
    dsn = dsn or settings.secrets.database_url
    if _pool is not None and _pool_dsn == dsn and not force:
        return
    if _pool is not None:
        await _pool.close()

    async def _init(conn: asyncpg.Connection) -> None:
        import json as _json

        await register_vector(conn)
        # jsonb/json come back as Python objects, not strings:
        await conn.set_type_codec("jsonb", encoder=_json.dumps, decoder=_json.loads, schema="pg_catalog")
        await conn.set_type_codec("json", encoder=_json.dumps, decoder=_json.loads, schema="pg_catalog")

    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=20, init=_init)
    _pool_dsn = dsn


async def close_pool() -> None:
    global _pool, _pool_dsn
    if _pool is not None:
        await _pool.close()
    _pool = None
    _pool_dsn = None


async def init_db(dsn: str | None = None) -> None:
    """Apply migrations, then open the pool. Idempotent."""
    await apply_migrations(dsn)
    await open_pool(dsn)


async def recover_interrupted_tasks() -> list[tuple[UUID, UUID]]:
    """System startup exception to tenant-first access: no action replay.

    A process crash leaves pending/running tasks and approvals behind. Mark
    them terminal; leave uncertain budget reservations untouched for separate
    reconciliation so an external side effect is never repeated blindly.
    """
    async with _require_pool().acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch(
                """UPDATE tasks SET status='failed',
                     result='interrupted by service restart; not replayed',
                     finished_at=now()
                   WHERE status IN ('pending','running','awaiting_approval')
                   RETURNING user_id,id"""
            )
            await conn.execute(
                """UPDATE approvals SET status='expired', decided_at=now()
                   WHERE status='pending'"""
            )
    return [(row["user_id"], row["id"]) for row in rows]


def _require_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("database pool not open — call core.db.init_db() first")
    return _pool


async def healthcheck() -> bool:
    """Cheap readiness check; never calls a paid or external provider."""
    if _pool is None:
        return False
    try:
        return await _pool.fetchval("SELECT 1") == 1
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Users & sessions
# --------------------------------------------------------------------------- #


async def create_user(
    email: str,
    password_hash: str | None = None,
    oauth_subject: str | None = None,
    plan_tier: str = "free",
    status: str = "active",
) -> User:
    row = await _require_pool().fetchrow(
        "INSERT INTO users (email, password_hash, oauth_subject, plan_tier, status) "
        "VALUES ($1, $2, $3, $4, $5) RETURNING *",
        email,
        password_hash,
        oauth_subject,
        plan_tier,
        status,
    )
    return _user(row)


async def get_user(user_id: UUID) -> User | None:
    row = await _require_pool().fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    return _user(row) if row else None


async def get_user_by_email(email: str) -> User | None:
    row = await _require_pool().fetchrow("SELECT * FROM users WHERE email = $1", email)
    return _user(row) if row else None


_USER_UPDATABLE = (
    "email",
    "password_hash",
    "plan_tier",
    "stripe_customer_id",
    "stripe_subscription_id",
    "billing_state",
    "billing_grace_until",
    "status",
    "oauth_subject",
    "user_limits_json",
    "settings_json",
    "timezone",
)


async def update_user(user_id: UUID, **fields: Any) -> User | None:
    bad = set(fields) - set(_USER_UPDATABLE)
    if bad:
        raise ValueError(f"update_user: cannot update {sorted(bad)}")
    if not fields:
        return await get_user(user_id)
    sets = ", ".join(f"{name} = ${i + 2}" for i, name in enumerate(fields))
    row = await _require_pool().fetchrow(
        f"UPDATE users SET {sets} WHERE id = $1 RETURNING *", user_id, *fields.values()
    )
    return _user(row) if row else None


async def get_purchase_policy(user_id: UUID) -> dict[str, Any]:
    row = await _require_pool().fetchrow("SELECT * FROM purchase_policies WHERE user_id=$1", user_id)
    return (
        dict(row)
        if row
        else {
            "user_id": user_id,
            "opted_in": False,
            "per_transaction_cap_usd": Decimal("0"),
            "monthly_cap_usd": Decimal("0"),
            "merchant_allowlist": [],
        }
    )


async def save_purchase_policy(
    user_id: UUID,
    per_transaction_cap_usd: Decimal,
    monthly_cap_usd: Decimal,
    merchant_allowlist: list[str],
) -> None:
    """Policy editing never opts a user into spending by itself."""
    await _require_pool().execute(
        """INSERT INTO purchase_policies
            (user_id, per_transaction_cap_usd, monthly_cap_usd, merchant_allowlist)
           VALUES ($1,$2,$3,$4)
           ON CONFLICT (user_id) DO UPDATE SET
             per_transaction_cap_usd=EXCLUDED.per_transaction_cap_usd,
             monthly_cap_usd=EXCLUDED.monthly_cap_usd,
             merchant_allowlist=EXCLUDED.merchant_allowlist,
             opted_in=false, updated_at=now()""",
        user_id,
        per_transaction_cap_usd,
        monthly_cap_usd,
        merchant_allowlist,
    )


async def record_purchase_denial(
    user_id: UUID,
    task_id: str,
    task_source: str,
    merchant: str | None,
    amount_usd: Decimal | None,
    description: str | None,
    outcome: str,
    reason: str,
) -> None:
    await _require_pool().execute(
        """INSERT INTO purchase_attempts
             (user_id,task_id,task_source,merchant,amount_usd,description,outcome,reason)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
        user_id,
        task_id[:100],
        task_source[:20],
        merchant[:200] if merchant else None,
        amount_usd,
        description[:300] if description else None,
        outcome,
        reason[:200],
    )


async def recent_purchase_attempts(user_id: UUID, limit: int = 10) -> list[dict[str, Any]]:
    rows = await _require_pool().fetch(
        """SELECT merchant,amount_usd,outcome,reason,created_at
           FROM purchase_attempts WHERE user_id=$1
           ORDER BY created_at DESC LIMIT $2""",
        user_id,
        min(limit, 50),
    )
    return [dict(row) for row in rows]


async def get_purchase_connection(user_id: UUID) -> dict[str, Any] | None:
    row = await _require_pool().fetchrow(
        "SELECT * FROM purchase_connections WHERE user_id=$1", user_id
    )
    return dict(row) if row else None


async def upsert_purchase_connection(
    user_id: UUID,
    provider: str,
    account_hint: str = "",
) -> dict[str, Any]:
    """Insert or refresh the ONE per-user payment connection. Reconnecting
    after a revoke bumps connection_version so in-flight purchases bound to
    the old version can no longer claim."""
    row = await _require_pool().fetchrow(
        """INSERT INTO purchase_connections (user_id, provider, account_hint, status, connected_at)
           VALUES ($1, $2, $3, 'active', now())
           ON CONFLICT (user_id) DO UPDATE SET
             provider=EXCLUDED.provider,
             account_hint=EXCLUDED.account_hint,
             status='active',
             connection_version=purchase_connections.connection_version + 1,
             connected_at=now(),
             revoked_at=NULL
           RETURNING *""",
        user_id,
        provider,
        account_hint[:50],
    )
    return dict(row)


async def revoke_purchase_connection(user_id: UUID) -> bool:
    row = await _require_pool().fetchrow(
        """UPDATE purchase_connections
           SET status='revoked', revoked_at=now(), connection_version=connection_version + 1
           WHERE user_id=$1 AND status='active' RETURNING *""",
        user_id,
    )
    return row is not None


async def set_purchase_opt_in(user_id: UUID, opted_in: bool) -> None:
    await _require_pool().execute(
        """INSERT INTO purchase_policies (user_id, opted_in) VALUES ($1, $2)
           ON CONFLICT (user_id) DO UPDATE SET opted_in=EXCLUDED.opted_in, updated_at=now()""",
        user_id,
        opted_in,
    )


# --------------------------------------------------------------------------- #
# Purchases: durable identity + lifecycle (migration 0008)
# --------------------------------------------------------------------------- #


def _purchase(row: asyncpg.Record) -> dict[str, Any]:
    return dict(row)


async def get_purchase_by_invocation(user_id: UUID, invocation_key: str) -> dict[str, Any] | None:
    row = await _require_pool().fetchrow(
        "SELECT * FROM purchases WHERE user_id=$1 AND invocation_key=$2", user_id, invocation_key
    )
    return _purchase(row) if row else None


async def get_purchase_by_order(user_id: UUID, order_ref: str) -> dict[str, Any] | None:
    row = await _require_pool().fetchrow(
        "SELECT * FROM purchases WHERE user_id=$1 AND order_ref=$2", user_id, order_ref[:200]
    )
    return _purchase(row) if row else None


async def count_purchases_for_task(user_id: UUID, task_id: str) -> int:
    return await _require_pool().fetchval(
        "SELECT count(*) FROM purchases WHERE user_id=$1 AND task_id=$2", user_id, task_id[:100]
    )


async def get_purchase(user_id: UUID, purchase_id: UUID) -> dict[str, Any] | None:
    row = await _require_pool().fetchrow(
        "SELECT * FROM purchases WHERE user_id=$1 AND id=$2", user_id, purchase_id
    )
    return _purchase(row) if row else None


async def create_purchase(
    user_id: UUID,
    task_id: str,
    task_source: str,
    invocation_key: str,
    merchant: str,
    merchant_input: str,
    amount: Decimal,
    currency: str,
    description: str,
    connection_version: int,
    order_ref: str | None,
    state: str,
    approval_expires_at: datetime | None,
) -> dict[str, Any]:
    row = await _require_pool().fetchrow(
        """INSERT INTO purchases
             (user_id,task_id,task_source,invocation_key,merchant,merchant_input,
              amount,currency,description,connection_version,order_ref,state,
              approval_expires_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) RETURNING *""",
        user_id,
        task_id[:100],
        task_source[:20],
        invocation_key,
        merchant,
        merchant_input[:200],
        amount,
        currency,
        description[:300],
        connection_version,
        order_ref[:200] if order_ref else None,
        state,
        approval_expires_at,
    )
    return _purchase(row)


async def transition_purchase(
    user_id: UUID,
    purchase_id: UUID,
    new_state: str,
    from_states: tuple[str, ...],
    **fields: Any,
) -> dict[str, Any] | None:
    """Guarded lifecycle transition: only from the allowed current states.
    Returns the updated row, or None when the purchase already moved on —
    callers treat that as 'someone else won', never as a fresh error."""
    allowed = ", ".join(f"${i + 4}" for i in range(len(from_states)))
    sets = ", ".join(f"{name} = ${len(from_states) + 4 + i}" for i, name in enumerate(fields))
    params: list[Any] = [user_id, purchase_id, new_state, *from_states, *fields.values()]
    sql = (
        f"UPDATE purchases SET state=$3, updated_at=now(){', ' + sets if fields else ''} "
        f"WHERE user_id=$1 AND id=$2 AND state IN ({allowed}) RETURNING *"
    )
    row = await _require_pool().fetchrow(sql, *params)
    return _purchase(row) if row else None


async def update_purchase(user_id: UUID, purchase_id: UUID, **fields: Any) -> None:
    """Field update WITHOUT a state change (e.g. attaching the approval id
    while the purchase stays awaiting_approval)."""
    if not fields:
        return
    sets = ", ".join(f"{name} = ${2 + i + 1}" for i, name in enumerate(fields))
    await _require_pool().execute(
        f"UPDATE purchases SET updated_at=now(), {sets} WHERE user_id=$1 AND id=$2",
        user_id,
        purchase_id,
        *fields.values(),
    )


async def record_purchase_event(
    user_id: UUID,
    purchase_id: UUID,
    event: str,
    detail: dict[str, Any] | None = None,
) -> None:
    await _require_pool().execute(
        "INSERT INTO purchase_events (purchase_id,user_id,event,detail) VALUES ($1,$2,$3,$4)",
        purchase_id,
        user_id,
        event[:50],
        detail or {},
    )


async def purchase_month_totals(user_id: UUID, month: date) -> dict[str, Decimal]:
    """Settled (succeeded) and reserved (executing/unknown) sums for one UTC
    month. Executing/unknown stay counted — an unfinished purchase still holds
    its budget until a provider lookup resolves it."""
    row = await _require_pool().fetchrow(
        """SELECT
             COALESCE(SUM(amount) FILTER (WHERE state='succeeded'), 0) AS settled,
             COALESCE(SUM(amount) FILTER (WHERE state IN ('executing','unknown')), 0) AS reserved
           FROM purchases WHERE user_id=$1 AND reservation_month=$2""",
        user_id,
        month,
    )
    return {"settled": Decimal(row["settled"]), "reserved": Decimal(row["reserved"])}


async def recent_purchases(user_id: UUID, limit: int = 5) -> list[dict[str, Any]]:
    rows = await _require_pool().fetch(
        """SELECT id,merchant,amount,currency,state,failure_reason,created_at
           FROM purchases WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2""",
        user_id,
        min(limit, 20),
    )
    return [dict(row) for row in rows]


async def claim_purchase(
    user_id: UUID,
    purchase_id: UUID,
    merchant: str,
    amount: Decimal,
    now: datetime,
) -> dict[str, Any]:
    """The one execution gate: a short per-user-locked transaction that re-reads
    every gate FRESH (opt-in, connection version, approval state/expiry,
    allowlist, both caps including existing reservations) and atomically flips
    the purchase to `executing` — which IS the reservation. Returns a dict:
    kind=claimed|denied|expired|conflict, reason, purchase.

    Lock anchor: the user's policy row (guaranteed present — a purchase can
    only be claimed for an opted-in user). Concurrent claimers serialize here;
    the ready→executing CAS makes a double claim impossible.
    """
    async with _require_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"purchase:{user_id}")
            policy = await conn.fetchrow(
                "SELECT * FROM purchase_policies WHERE user_id=$1 FOR UPDATE", user_id
            )
            purchase = await conn.fetchrow(
                "SELECT * FROM purchases WHERE user_id=$1 AND id=$2", user_id, purchase_id
            )
            if policy is None or purchase is None:
                return {"kind": "conflict", "reason": "purchase not found", "purchase": None}
            if purchase["state"] != "ready":
                return {
                    "kind": "conflict",
                    "reason": f"purchase is {purchase['state']}, not ready",
                    "purchase": dict(purchase),
                }

            def deny(kind: str, reason: str) -> dict[str, Any]:
                return {"kind": kind, "reason": reason, "purchase": dict(purchase)}

            if not settings.payments.enabled or not settings.payments.provider:
                return deny("denied", "purchases were disabled before execution")
            user = await conn.fetchrow("SELECT status, plan_tier FROM users WHERE id=$1", user_id)
            if user is None or user["status"] != "active":
                return deny("denied", "account is not active")
            plan = settings.plan_for(user["plan_tier"])
            if not plan.payments_enabled:
                return deny("denied", f"payments not enabled on the {user['plan_tier']} plan")
            if not policy["opted_in"]:
                return deny("denied", "purchases are opted out")
            connection = await conn.fetchrow(
                "SELECT * FROM purchase_connections WHERE user_id=$1", user_id
            )
            if (
                connection is None
                or connection["status"] != "active"
                or connection["provider"] != settings.payments.provider
                or connection["connection_version"] != purchase["connection_version"]
            ):
                return deny("denied", "the payment connection changed — approve again after reconnecting")
            if merchant not in (policy["merchant_allowlist"] or []):
                return deny("denied", "merchant is no longer allowlisted")
            if amount > policy["per_transaction_cap_usd"]:
                return deny("denied", "amount now exceeds your per-transaction cap")
            month = now.date().replace(day=1)
            totals = await conn.fetchrow(
                """SELECT COALESCE(SUM(amount) FILTER (WHERE state IN ('succeeded','executing','unknown')), 0)
                   AS committed FROM purchases
                   WHERE user_id=$1 AND reservation_month=$2 AND id <> $3""",
                user_id,
                month,
                purchase_id,
            )
            if Decimal(totals["committed"]) + amount > policy["monthly_cap_usd"]:
                return deny("denied", "amount now exceeds your remaining monthly cap")
            if purchase["approval_id"] is not None:
                approval = await conn.fetchrow(
                    "SELECT status FROM approvals WHERE id=$1 AND user_id=$2",
                    purchase["approval_id"],
                    user_id,
                )
                if approval is None or approval["status"] != "approved":
                    return deny("denied", "the approval for this purchase is no longer granted")
                if purchase["approval_expires_at"] is not None and now > purchase["approval_expires_at"]:
                    return deny("expired", "the approval for this purchase expired")
            updated = await conn.fetchrow(
                """UPDATE purchases SET state='executing', reservation_month=$3, updated_at=now()
                   WHERE user_id=$1 AND id=$2 AND state='ready' RETURNING *""",
                user_id,
                purchase_id,
                month,
            )
            if updated is None:
                return deny("conflict", "purchase already claimed")
            return {"kind": "claimed", "reason": None, "purchase": dict(updated)}


async def unresolved_purchases(limit: int = 20) -> list[dict[str, Any]]:
    """Purchases stuck in executing/unknown — startup + scheduler-tick
    reconciliation input. THE cross-tenant query for this table, same
    documented exception as due_jobs: it returns rows only to the system
    reconciler, which re-scopes every write by user_id."""
    rows = await _require_pool().fetch(
        """SELECT * FROM purchases WHERE state IN ('executing','unknown')
           ORDER BY updated_at LIMIT $1""",
        min(limit, 100),
    )
    return [dict(row) for row in rows]


async def create_session(user_id: UUID, token_hash: str, expires_at: datetime) -> SessionInfo:
    row = await _require_pool().fetchrow(
        "INSERT INTO sessions (user_id, token_hash, expires_at) VALUES ($1, $2, $3) RETURNING *",
        user_id,
        token_hash,
        expires_at,
    )
    return SessionInfo(**dict(row))


async def get_session_by_token_hash(token_hash: str) -> tuple[SessionInfo, User] | None:
    """Resolve a session hash to (session, user). Expired sessions read as absent."""
    row = await _require_pool().fetchrow(
        "SELECT s.id AS s_id, s.user_id AS s_user_id, s.token_hash AS s_token_hash, "
        "       s.expires_at AS s_expires_at, s.created_at AS s_created_at, u.* "
        "FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = $1 AND s.expires_at > now()",
        token_hash,
    )
    if row is None:
        return None
    session = SessionInfo(
        id=row["s_id"],
        user_id=row["s_user_id"],
        token_hash=row["s_token_hash"],
        expires_at=row["s_expires_at"],
        created_at=row["s_created_at"],
    )
    user = _user(row)
    return session, user


async def delete_session(token_hash: str) -> None:
    await _require_pool().execute("DELETE FROM sessions WHERE token_hash = $1", token_hash)


async def get_chats_for_user(user_id: UUID) -> list[str]:
    """Telegram chats linked to this user (for gateway delivery)."""
    rows = await _require_pool().fetch(
        "SELECT telegram_chat_id FROM telegram_links WHERE user_id = $1", user_id
    )
    return [r["telegram_chat_id"] for r in rows]


# --------------------------------------------------------------------------- #
# Telegram link codes (gateway/account_linking.py) — hash-stored, single-use
# --------------------------------------------------------------------------- #


async def create_link_code(code_hash: str, user_id: UUID, expires_at: datetime) -> None:
    await _require_pool().execute(
        "INSERT INTO link_codes (code_hash, user_id, expires_at) VALUES ($1, $2, $3) "
        "ON CONFLICT (code_hash) DO UPDATE SET user_id = EXCLUDED.user_id, "
        "expires_at = EXCLUDED.expires_at, used_at = NULL",
        code_hash,
        user_id,
        expires_at,
    )


async def consume_link_code(code_hash: str) -> UUID | None:
    """Atomically redeem a code. None if unknown, used, or expired."""
    row = await _require_pool().fetchrow(
        "UPDATE link_codes SET used_at = now() "
        "WHERE code_hash = $1 AND used_at IS NULL AND expires_at > now() "
        "RETURNING user_id",
        code_hash,
    )
    return row["user_id"] if row else None


async def delete_sessions_for_user(user_id: UUID) -> int:
    """Invalidate every session for a user (used by password reset)."""
    tag = await _require_pool().execute("DELETE FROM sessions WHERE user_id = $1", user_id)
    return int(tag.split()[-1])


# --------------------------------------------------------------------------- #
# Auth tokens (single-use, server-tracked)
# --------------------------------------------------------------------------- #


async def create_auth_token(user_id: UUID, kind: str, jti: str, expires_at: datetime) -> None:
    await _require_pool().execute(
        "INSERT INTO auth_tokens (user_id, kind, jti, expires_at) VALUES ($1, $2, $3, $4)",
        user_id,
        kind,
        jti,
        expires_at,
    )


async def consume_auth_token(user_id: UUID, jti: str) -> bool:
    """Atomically mark a token used. False if unknown, used, or expired."""
    row = await _require_pool().fetchrow(
        "UPDATE auth_tokens SET used_at = now() "
        "WHERE jti = $1 AND user_id = $2 AND used_at IS NULL AND expires_at > now() "
        "RETURNING id",
        jti,
        user_id,
    )
    return row is not None


# --------------------------------------------------------------------------- #
# Tasks
# --------------------------------------------------------------------------- #


def _task(row: asyncpg.Record) -> Task:
    return Task(**dict(row))


async def create_task(user_id: UUID, request: str, source: str, parent_job_id: UUID | None = None) -> Task:
    row = await _require_pool().fetchrow(
        "INSERT INTO tasks (user_id, request, source, parent_job_id) VALUES ($1, $2, $3, $4) RETURNING *",
        user_id,
        request,
        source,
        parent_job_id,
    )
    return _task(row)


_TASK_UPDATABLE = ("status", "result", "steps_json", "cost_usd", "started_at", "finished_at")


async def update_task(user_id: UUID, task_id: UUID, **fields: Any) -> Task | None:
    """Update a task row. Returns None (and changes nothing) if the task does
    not belong to this user — cross-tenant updates are structurally impossible."""
    bad = set(fields) - set(_TASK_UPDATABLE)
    if bad:
        raise ValueError(f"update_task: cannot update {sorted(bad)}")
    if not fields:
        return await get_task(user_id, task_id)
    sets = ", ".join(f"{name} = ${i + 3}" for i, name in enumerate(fields))
    row = await _require_pool().fetchrow(
        f"UPDATE tasks SET {sets} WHERE user_id = $1 AND id = $2 RETURNING *",
        user_id,
        task_id,
        *fields.values(),
    )
    return _task(row) if row else None


async def get_task(user_id: UUID, task_id: UUID) -> Task | None:
    row = await _require_pool().fetchrow(
        "SELECT * FROM tasks WHERE user_id = $1 AND id = $2", user_id, task_id
    )
    return _task(row) if row else None


async def list_tasks(user_id: UUID, limit: int = 50, offset: int = 0) -> list[Task]:
    rows = await _require_pool().fetch(
        "SELECT * FROM tasks WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
        user_id,
        limit,
        offset,
    )
    return [_task(r) for r in rows]


# --------------------------------------------------------------------------- #
# Memories
# --------------------------------------------------------------------------- #


def _memory(row: asyncpg.Record) -> Memory:
    data = dict(row)
    data["embedding"] = _embedding(data.get("embedding"))
    return Memory(**data)


async def add_memory(
    user_id: UUID,
    content: str,
    category: str,
    embedding: list[float],
    importance: float = 0.5,
) -> Memory:
    row = await _require_pool().fetchrow(
        "INSERT INTO memories (user_id, content, category, embedding, importance) "
        "VALUES ($1, $2, $3, $4, $5) RETURNING *",
        user_id,
        content,
        category,
        Vector(embedding),
        importance,
    )
    return _memory(row)


async def search_memories(user_id: UUID, embedding: list[float], limit: int = 10) -> list[Memory]:
    """Nearest memories FOR THIS USER ONLY, by cosine distance."""
    rows = await _require_pool().fetch(
        "SELECT *, embedding <=> $2::vector AS distance "
        "FROM memories WHERE user_id = $1 "
        "ORDER BY embedding <=> $2::vector LIMIT $3",
        user_id,
        Vector(embedding),
        limit,
    )
    memories = []
    for r in rows:
        m = _memory(r)
        m.distance = float(r["distance"])
        memories.append(m)
    return memories


async def get_memory(user_id: UUID, memory_id: UUID) -> Memory | None:
    row = await _require_pool().fetchrow(
        "SELECT * FROM memories WHERE user_id = $1 AND id = $2", user_id, memory_id
    )
    return _memory(row) if row else None


async def delete_memory(user_id: UUID, memory_id: UUID) -> bool:
    """Delete the user's own memory. False (and no effect) for anyone else's."""
    tag = await _require_pool().execute(
        "DELETE FROM memories WHERE user_id = $1 AND id = $2", user_id, memory_id
    )
    return tag.split()[-1] == "1"


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #


def _job(row: asyncpg.Record) -> Job:
    return Job(**dict(row))


async def create_job(
    user_id: UUID,
    kind: str,
    schedule: str,
    check_mode: str,
    instruction: str,
    check_script_path: str | None = None,
    next_run_at: datetime | None = None,
    created_by_task: UUID | None = None,
    state_json: dict[str, Any] | None = None,
) -> Job:
    row = await _require_pool().fetchrow(
        "INSERT INTO jobs (user_id, kind, schedule, check_mode, instruction, "
        "check_script_path, next_run_at, created_by_task, state_json) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING *",
        user_id,
        kind,
        schedule,
        check_mode,
        instruction,
        check_script_path,
        next_run_at,
        created_by_task,
        state_json or {},
    )
    return _job(row)


_JOB_UPDATABLE = (
    "active",
    "next_run_at",
    "last_run_at",
    "state_json",
    "schedule",
    "instruction",
    "check_mode",
    "check_script_path",
)


async def update_job(user_id: UUID, job_id: UUID, **fields: Any) -> Job | None:
    bad = set(fields) - set(_JOB_UPDATABLE)
    if bad:
        raise ValueError(f"update_job: cannot update {sorted(bad)}")
    if not fields:
        return await get_job(user_id, job_id)
    sets = ", ".join(f"{name} = ${i + 3}" for i, name in enumerate(fields))
    row = await _require_pool().fetchrow(
        f"UPDATE jobs SET {sets} WHERE user_id = $1 AND id = $2 RETURNING *",
        user_id,
        job_id,
        *fields.values(),
    )
    return _job(row) if row else None


async def get_job(user_id: UUID, job_id: UUID) -> Job | None:
    row = await _require_pool().fetchrow("SELECT * FROM jobs WHERE user_id = $1 AND id = $2", user_id, job_id)
    return _job(row) if row else None


async def list_jobs(user_id: UUID) -> list[Job]:
    rows = await _require_pool().fetch("SELECT * FROM jobs WHERE user_id = $1 ORDER BY created_at", user_id)
    return [_job(r) for r in rows]


async def due_jobs(now: datetime) -> list[Job]:
    """THE one deliberately cross-tenant function in the codebase.

    The scheduler service's entire job is to span users and find whatever is
    due; it never returns one user's data to another — it only launches
    per-user tasks. Claiming happens under a transaction-scoped advisory lock
    with FOR UPDATE SKIP LOCKED so two concurrent ticks can never double-fire
    a job; the caller must advance next_run_at immediately after claiming.
    """
    pool = _require_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            got_lock = await conn.fetchval("SELECT pg_try_advisory_xact_lock(hashtext('core.db.due_jobs'))")
            if not got_lock:
                return []
            rows = await conn.fetch(
                "SELECT * FROM jobs "
                "WHERE active AND next_run_at IS NOT NULL AND next_run_at <= $1 "
                "ORDER BY next_run_at "
                "FOR UPDATE SKIP LOCKED",
                now,
            )
    return [_job(r) for r in rows]


async def count_active_jobs(user_id: UUID) -> int:
    """How many of this user's jobs are currently active (plan cap check)."""
    value = await _require_pool().fetchval("SELECT COUNT(*) FROM jobs WHERE user_id = $1 AND active", user_id)
    return int(value)


async def delete_job(user_id: UUID, job_id: UUID) -> bool:
    """Delete the user's own job. False (and no effect) for anyone else's."""
    tag = await _require_pool().execute("DELETE FROM jobs WHERE user_id = $1 AND id = $2", user_id, job_id)
    return tag.split()[-1] == "1"


async def advance_job_fire(
    user_id: UUID,
    job_id: UUID,
    expected_next_run_at: datetime,
    new_next_run_at: datetime,
    fired_at: datetime,
) -> bool:
    """Atomically claim a due fire: move next_run_at forward and stamp
    last_run_at, but only if next_run_at still holds the value the scheduler
    claimed from due_jobs. False means another tick got there first — the
    caller must not fire the job (no double-fires, ever)."""
    row = await _require_pool().fetchrow(
        "UPDATE jobs SET next_run_at = $4, last_run_at = $5 "
        "WHERE user_id = $1 AND id = $2 AND next_run_at = $3 RETURNING id",
        user_id,
        job_id,
        expected_next_run_at,
        new_next_run_at,
        fired_at,
    )
    return row is not None


# --------------------------------------------------------------------------- #
# Skills meta (per-user skill library stats; folders live on disk, core/skills.py)
# --------------------------------------------------------------------------- #


def _skill_meta(row: asyncpg.Record) -> SkillMeta:
    return SkillMeta(**dict(row))


async def save_skill_meta(user_id: UUID, name: str) -> SkillMeta:
    """Insert-if-absent; re-saving an existing skill clears needs_review."""
    row = await _require_pool().fetchrow(
        "INSERT INTO skills_meta (user_id, name) VALUES ($1, $2) "
        "ON CONFLICT (user_id, name) DO UPDATE SET reviewed = true "
        "RETURNING *",
        user_id,
        name,
    )
    return _skill_meta(row)


async def get_skill_meta(user_id: UUID, name: str) -> SkillMeta | None:
    row = await _require_pool().fetchrow(
        "SELECT * FROM skills_meta WHERE user_id = $1 AND name = $2", user_id, name
    )
    return _skill_meta(row) if row else None


async def list_skill_meta(user_id: UUID) -> list[SkillMeta]:
    rows = await _require_pool().fetch(
        "SELECT * FROM skills_meta WHERE user_id = $1 ORDER BY created_at", user_id
    )
    return [_skill_meta(r) for r in rows]


async def record_skill_use(user_id: UUID, name: str, ok: bool) -> SkillMeta:
    """Count one run of the user's skill and apply the failure-rate guard:
    once failures >= 3 AND more than half the runs failed, the skill is
    flagged needs_review (reviewed=false) — flagged, never deleted."""
    ok_int = 1 if ok else 0
    row = await _require_pool().fetchrow(
        "INSERT INTO skills_meta (user_id, name, uses, successes, failures, last_used_at) "
        "VALUES ($1, $2, 1, $3, $4, now()) "
        "ON CONFLICT (user_id, name) DO UPDATE SET "
        "uses = skills_meta.uses + 1, "
        "successes = skills_meta.successes + $3, "
        "failures = skills_meta.failures + $4, "
        "last_used_at = now() "
        "RETURNING *",
        user_id,
        name,
        ok_int,
        1 - ok_int,
    )
    meta = _skill_meta(row)
    if meta.failures >= 3 and meta.uses > 0 and meta.failures / meta.uses > 0.5:
        row = await _require_pool().fetchrow(
            "UPDATE skills_meta SET reviewed = false WHERE user_id = $1 AND name = $2 RETURNING *",
            user_id,
            name,
        )
        meta = _skill_meta(row)
    return meta


# --------------------------------------------------------------------------- #
# Approvals
# --------------------------------------------------------------------------- #


def _approval(row: asyncpg.Record) -> Approval:
    return Approval(**dict(row))


async def record_approval(
    user_id: UUID, task_id: UUID | None, action_summary: str, details_json: dict[str, Any]
) -> Approval:
    row = await _require_pool().fetchrow(
        "INSERT INTO approvals (user_id, task_id, action_summary, details_json) "
        "VALUES ($1, $2, $3, $4) RETURNING *",
        user_id,
        task_id,
        action_summary,
        details_json,
    )
    return _approval(row)


async def update_approval(user_id: UUID, approval_id: UUID, status: str) -> Approval | None:
    """Decide an approval. Only the owning user's id can resolve their own
    approval — a decision referencing another user's approval id is a no-op."""
    if status not in ("approved", "denied", "expired"):
        raise ValueError(f"update_approval: bad status {status!r}")
    row = await _require_pool().fetchrow(
        "UPDATE approvals SET status = $3, decided_at = now() "
        "WHERE user_id = $1 AND id = $2 AND status = 'pending' RETURNING *",
        user_id,
        approval_id,
        status,
    )
    return _approval(row) if row else None


# --------------------------------------------------------------------------- #
# Money: agent-directed spending (spend_log) — Phase 6 fills the callers
# --------------------------------------------------------------------------- #


def _spend(row: asyncpg.Record) -> SpendEntry:
    return SpendEntry(**dict(row))


async def log_spend(
    user_id: UUID,
    merchant: str,
    amount: Decimal,
    currency: str = "usd",
    approved_by: str = "auto",
    status: str = "completed",
    task_id: UUID | None = None,
) -> SpendEntry:
    row = await _require_pool().fetchrow(
        "INSERT INTO spend_log (user_id, merchant, amount, currency, approved_by, status, task_id) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *",
        user_id,
        merchant,
        amount,
        currency,
        approved_by,
        status,
        task_id,
    )
    return _spend(row)


async def spend_this_month(user_id: UUID) -> Decimal:
    """Total completed agent-directed spending this calendar month (this user only)."""
    month_start, _ = _current_period()
    value = await _require_pool().fetchval(
        "SELECT COALESCE(SUM(amount), 0) FROM spend_log "
        "WHERE user_id = $1 AND status = 'completed' AND created_at >= $2",
        user_id,
        month_start,
    )
    return Decimal(value)


# --------------------------------------------------------------------------- #
# Money: platform usage metering (api_costs / usage_periods) — feeds billing
# --------------------------------------------------------------------------- #


def _current_period() -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt


async def log_api_cost(
    user_id: UUID,
    task_id: UUID | None,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: Decimal = Decimal("0"),
    operation_key: str | None = None,
) -> None:
    await _require_pool().execute(
        "INSERT INTO api_costs "
        "(user_id, task_id, model, input_tokens, output_tokens, cost_usd, operation_key) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) "
        "ON CONFLICT (user_id, operation_key) WHERE operation_key IS NOT NULL DO NOTHING",
        user_id,
        task_id,
        model,
        input_tokens,
        output_tokens,
        cost_usd,
        operation_key,
    )


async def task_cost(user_id: UUID, task_id: UUID) -> Decimal:
    value = await _require_pool().fetchval(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM api_costs WHERE user_id = $1 AND task_id = $2",
        user_id,
        task_id,
    )
    return Decimal(value)


async def reserve_budget(
    user_id: UUID,
    task_id: UUID | None,
    operation_key: str,
    max_amount: Decimal,
    allow_partial: bool = True,
) -> Decimal:
    """Reserve up to max_amount under the user's current hard cap.

    Locks only the user's row. The caller must supply a server-owned, stable
    operation key and must not hold this transaction across network I/O.
    """
    if max_amount <= 0:
        raise ValueError("budget reservation must be positive")
    start, end = _current_period()
    async with _require_pool().acquire() as con:
        async with con.transaction():
            user = await con.fetchrow("SELECT * FROM users WHERE id = $1 FOR UPDATE", user_id)
            if user is None:
                raise ValueError("unknown user")
            old = await con.fetchrow(
                "SELECT amount_usd, state FROM budget_reservations WHERE user_id = $1 AND operation_key = $2",
                user_id,
                operation_key,
            )
            if old:
                if old["state"] == "settled":
                    raise ValueError("billable operation already completed")
                return Decimal(old["amount_usd"])
            settled = Decimal(
                await con.fetchval(
                    "SELECT COALESCE(SUM(cost_usd), 0) FROM api_costs "
                    "WHERE user_id = $1 AND created_at >= $2 AND created_at < $3",
                    user_id,
                    start,
                    end,
                )
            )
            reserved = Decimal(
                await con.fetchval(
                    "SELECT COALESCE(SUM(amount_usd), 0) FROM budget_reservations "
                    "WHERE user_id = $1 AND period_start = $2 AND state IN ('reserved', 'unknown')",
                    user_id,
                    start.date(),
                )
            )
            from core.billing import _effective_plan

            cap = settings.plan_for(_effective_plan(_user(user))).hard_cap_usd
            amount = min(max_amount, cap - settled - reserved)
            if amount <= 0 or (not allow_partial and amount < max_amount):
                return Decimal("0")
            await con.execute(
                "INSERT INTO budget_reservations "
                "(user_id, task_id, operation_key, period_start, amount_usd) "
                "VALUES ($1, $2, $3, $4, $5)",
                user_id,
                task_id,
                operation_key,
                start.date(),
                amount,
            )
            return amount


async def settle_budget(
    user_id: UUID,
    operation_key: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: Decimal,
    itemized: list[tuple[str, int, int, Decimal]] | None = None,
) -> bool:
    """Idempotently write actual cost and settle its reservation together."""
    async with _require_pool().acquire() as con:
        async with con.transaction():
            row = await con.fetchrow(
                "SELECT task_id, state FROM budget_reservations "
                "WHERE user_id = $1 AND operation_key = $2 FOR UPDATE",
                user_id,
                operation_key,
            )
            if row is None:
                raise ValueError("missing budget reservation")
            if row["state"] == "settled":
                return False
            lines = itemized or [(model, input_tokens, output_tokens, cost_usd)]
            if sum((line[3] for line in lines), Decimal("0")) != cost_usd:
                raise ValueError("itemized model costs do not match result total")
            for index, (line_model, line_input, line_output, line_cost) in enumerate(lines):
                key = f"{operation_key}:{index}" if itemized else operation_key
                await con.execute(
                    "INSERT INTO api_costs "
                    "(user_id, task_id, model, input_tokens, output_tokens, cost_usd, operation_key) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7) "
                    "ON CONFLICT (user_id, operation_key) WHERE operation_key IS NOT NULL DO NOTHING",
                    user_id,
                    row["task_id"],
                    line_model,
                    line_input,
                    line_output,
                    line_cost,
                    key,
                )
            await con.execute(
                "UPDATE budget_reservations SET state = 'settled', updated_at = now() "
                "WHERE user_id = $1 AND operation_key = $2",
                user_id,
                operation_key,
            )
            return True


async def mark_budget_unknown(user_id: UUID, operation_key: str) -> None:
    await _require_pool().execute(
        "UPDATE budget_reservations SET state = 'unknown', updated_at = now() "
        "WHERE user_id = $1 AND operation_key = $2 AND state = 'reserved'",
        user_id,
        operation_key,
    )


async def release_unsubmitted_budget(user_id: UUID, operation_key: str) -> None:
    """Release only when failure happened before a provider call was possible."""
    await _require_pool().execute(
        "DELETE FROM budget_reservations WHERE user_id = $1 AND operation_key = $2 AND state = 'reserved'",
        user_id,
        operation_key,
    )


async def reserved_this_period(user_id: UUID) -> Decimal:
    start, _ = _current_period()
    value = await _require_pool().fetchval(
        "SELECT COALESCE(SUM(amount_usd), 0) FROM budget_reservations "
        "WHERE user_id = $1 AND period_start = $2 AND state IN ('reserved', 'unknown')",
        user_id,
        start.date(),
    )
    return Decimal(value)


async def record_billing_warning(user_id: UUID, period_start: date, threshold: int) -> bool:
    tag = await _require_pool().execute(
        "INSERT INTO billing_warnings (user_id, period_start, threshold) "
        "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
        user_id,
        period_start,
        threshold,
    )
    return tag == "INSERT 0 1"


async def get_user_by_stripe_customer(customer_id: str) -> User | None:
    """Service-only exception: a verified Stripe webhook supplies the customer id.

    Never call this with a browser/model-provided id. The route validates the
    Stripe signature before reaching this lookup.
    """
    row = await _require_pool().fetchrow("SELECT * FROM users WHERE stripe_customer_id = $1", customer_id)
    return _user(row) if row else None


async def apply_stripe_event(
    user_id: UUID,
    event_id: str,
    event_type: str,
    subscription_id: str | None,
    state: str,
    tier: str,
    grace_until: datetime | None,
) -> bool:
    """Atomically dedupe a verified event and replace the user's entitlement."""
    async with _require_pool().acquire() as con:
        async with con.transaction():
            await con.fetchrow("SELECT id FROM users WHERE id = $1 FOR UPDATE", user_id)
            tag = await con.execute(
                "INSERT INTO processed_stripe_events(event_id, event_type) "
                "VALUES ($1, $2) ON CONFLICT DO NOTHING",
                event_id,
                event_type,
            )
            if tag != "INSERT 0 1":
                return False
            await con.execute(
                "UPDATE users SET stripe_subscription_id = $2, billing_state = $3, "
                "plan_tier = $4, billing_grace_until = $5 WHERE id = $1",
                user_id,
                subscription_id,
                state,
                tier,
                grace_until,
            )
            return True


async def set_stripe_customer(user_id: UUID, customer_id: str) -> User:
    row = await _require_pool().fetchrow(
        "UPDATE users SET stripe_customer_id = $2 WHERE id = $1 AND stripe_customer_id IS NULL RETURNING *",
        user_id,
        customer_id,
    )
    if row:
        return _user(row)
    user = await get_user(user_id)
    if user is None:
        raise ValueError("unknown user")
    return user


async def save_billing_operation(user_id: UUID, kind: str, operation_key: str, provider_id: str) -> str:
    row = await _require_pool().fetchrow(
        "INSERT INTO billing_operations(user_id, kind, operation_key, provider_id) "
        "VALUES ($1, $2, $3, $4) ON CONFLICT (user_id, kind, operation_key) "
        "DO UPDATE SET provider_id = COALESCE(billing_operations.provider_id, EXCLUDED.provider_id) "
        "RETURNING provider_id",
        user_id,
        kind,
        operation_key,
        provider_id,
    )
    return row["provider_id"]


async def get_billing_operation(user_id: UUID, kind: str, operation_key: str) -> str | None:
    return await _require_pool().fetchval(
        "SELECT provider_id FROM billing_operations WHERE user_id = $1 AND kind = $2 AND operation_key = $3",
        user_id,
        kind,
        operation_key,
    )


async def cost_today(user_id: UUID) -> Decimal:
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    value = await _require_pool().fetchval(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM api_costs WHERE user_id = $1 AND created_at >= $2",
        user_id,
        midnight,
    )
    return Decimal(value)


async def active_usage_user_ids() -> list[UUID]:
    """Service-only cross-tenant exception for the hourly billing rollup.

    Returns user IDs only. The scheduler then calls tenant-scoped rollup for
    each one, and never returns one tenant's totals to another tenant.
    """
    start, _ = _current_period()
    rows = await _require_pool().fetch("SELECT DISTINCT user_id FROM api_costs WHERE created_at >= $1", start)
    return [row["user_id"] for row in rows]


async def usage_this_period(user_id: UUID) -> UsageSummary:
    """Live usage for this user's current calendar month vs their plan."""
    user = await get_user(user_id)
    if user is None:
        raise ValueError(f"usage_this_period: no user {user_id}")
    plan = settings.plan_for(user.plan_tier)
    start, next_start = _current_period()
    total = await _require_pool().fetchval(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM api_costs "
        "WHERE user_id = $1 AND created_at >= $2 AND created_at < $3",
        user_id,
        start,
        next_start,
    )
    total = Decimal(total)
    included = Decimal(plan.monthly_included_usage_usd)
    return UsageSummary(
        period_start=start.date(),
        period_end=(next_start - timedelta(days=1)).date(),
        total_cost=total,
        included_allowance=included,
        overage=max(Decimal("0"), total - included),
        plan_tier=user.plan_tier,
    )


async def upsert_usage_period(
    user_id: UUID,
    period_start: date,
    period_end: date,
    total_cost: Decimal,
    included_allowance: Decimal,
    overage: Decimal,
) -> UsagePeriod:
    row = await _require_pool().fetchrow(
        "INSERT INTO usage_periods (user_id, period_start, period_end, total_cost, "
        "included_allowance, overage, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, now()) "
        "ON CONFLICT (user_id, period_start) DO UPDATE SET "
        "period_end = EXCLUDED.period_end, total_cost = EXCLUDED.total_cost, "
        "included_allowance = EXCLUDED.included_allowance, overage = EXCLUDED.overage, "
        "updated_at = now() RETURNING *",
        user_id,
        period_start,
        period_end,
        total_cost,
        included_allowance,
        overage,
    )
    return UsagePeriod(**dict(row))


# --------------------------------------------------------------------------- #
# Vault entries (encryption itself arrives in Phase 4 — storage only here)
# --------------------------------------------------------------------------- #


def _vault(row: asyncpg.Record) -> VaultEntry:
    data = dict(row)
    blob = data["encrypted_blob"]
    data["encrypted_blob"] = bytes(blob)
    return VaultEntry(**data)


async def create_vault_entry(user_id: UUID, site: str, encrypted_blob: bytes) -> VaultEntry:
    row = await _require_pool().fetchrow(
        "INSERT INTO vault_entries (user_id, site, encrypted_blob) VALUES ($1, $2, $3) "
        "ON CONFLICT (user_id, site) DO UPDATE SET "
        "encrypted_blob = EXCLUDED.encrypted_blob, updated_at = now() RETURNING *",
        user_id,
        site,
        encrypted_blob,
    )
    return _vault(row)


async def get_vault_entry(user_id: UUID, site: str) -> VaultEntry | None:
    row = await _require_pool().fetchrow(
        "SELECT * FROM vault_entries WHERE user_id = $1 AND site = $2", user_id, site
    )
    return _vault(row) if row else None


async def list_vault_sites(user_id: UUID) -> list[str]:
    rows = await _require_pool().fetch(
        "SELECT site FROM vault_entries WHERE user_id = $1 ORDER BY site", user_id
    )
    return [r["site"] for r in rows]


async def delete_vault_entry(user_id: UUID, site: str) -> bool:
    """Remove the user's own credential for a site. False for foreign rows."""
    tag = await _require_pool().execute(
        "DELETE FROM vault_entries WHERE user_id = $1 AND site = $2", user_id, site
    )
    return tag.split()[-1] == "1"


async def get_vault_key(user_id: UUID) -> bytes | None:
    """The user's wrapped data key (still encrypted; unwrapping is core/
    secrets_vault.py's job)."""
    row = await _require_pool().fetchrow("SELECT wrapped_key FROM vault_keys WHERE user_id = $1", user_id)
    return bytes(row["wrapped_key"]) if row else None


async def create_vault_key(user_id: UUID, wrapped_key: bytes) -> bytes:
    """Store the user's wrapped data key; first write wins. Returns the
    stored wrapped key (so a lost race returns the existing key's holder's
    value and the caller re-reads instead of forking the key)."""
    row = await _require_pool().fetchrow(
        "INSERT INTO vault_keys (user_id, wrapped_key) VALUES ($1, $2) "
        "ON CONFLICT (user_id) DO UPDATE SET user_id = EXCLUDED.user_id "
        "RETURNING wrapped_key",
        user_id,
        wrapped_key,
    )
    return bytes(row["wrapped_key"])
