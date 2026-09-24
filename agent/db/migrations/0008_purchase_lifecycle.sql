-- Phase 6: durable purchase identity, lifecycle, and connection references.
-- Runtime purchases remain disabled: no provider adapter ships, so no row in
-- `purchases` can ever reach `executing` in production. The ledger exists so
-- the full path is testable against a clearly labeled TEST-ONLY fake.
--
-- `spend_log` (0001) is superseded by `purchases` for the purchase lifecycle:
-- it cannot express awaiting_approval/executing/unknown states, provider
-- idempotency bindings, or reservation periods. It is left in place, unused.

CREATE TABLE purchase_connections (
    user_id            uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    provider           text NOT NULL,
    -- Non-secret hint only (e.g. "•••4242"); real credentials would live in
    -- the per-user vault. No provider exists, so nothing is stored today.
    account_hint       text NOT NULL DEFAULT '',
    connection_version integer NOT NULL DEFAULT 1,
    status             text NOT NULL DEFAULT 'active'
                       CHECK (status IN ('active', 'revoked')),
    connected_at       timestamptz NOT NULL DEFAULT now(),
    revoked_at         timestamptz
);

CREATE TABLE purchases (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id            text NOT NULL,
    task_source        text NOT NULL,
    -- Server-owned replay binding: derived from trusted context + validated
    -- immutable details; the model cannot supply or invent it.
    invocation_key     text NOT NULL,
    order_ref          text,
    merchant           text NOT NULL,      -- canonical registrable domain
    merchant_input     text NOT NULL,      -- exactly what the caller passed
    recipient          text,
    amount             numeric(12,2) NOT NULL CHECK (amount > 0),
    currency           text NOT NULL DEFAULT 'USD',
    description        text NOT NULL,
    connection_version integer NOT NULL,
    state              text NOT NULL DEFAULT 'awaiting_approval'
                       CHECK (state IN ('awaiting_approval', 'ready', 'executing',
                                        'succeeded', 'failed', 'unknown',
                                        'denied', 'expired')),
    approval_id        uuid REFERENCES approvals(id) ON DELETE SET NULL,
    approval_expires_at timestamptz,
    provider           text,
    provider_ref       text,               -- durable provider transaction ref
    -- UTC month this purchase's reservation counts against; preserved across
    -- month-boundary reconciliation so budget cannot leak between months.
    reservation_month  date,
    failure_reason     text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, invocation_key)
);
CREATE INDEX idx_purchases_user_created ON purchases(user_id, created_at DESC);
CREATE INDEX idx_purchases_user_state ON purchases(user_id, state);
CREATE INDEX idx_purchases_reservation_month ON purchases(reservation_month)
    WHERE state IN ('executing', 'unknown', 'succeeded');
CREATE INDEX idx_purchases_unresolved ON purchases(updated_at)
    WHERE state IN ('executing', 'unknown');

CREATE TABLE purchase_events (
    id          bigserial PRIMARY KEY,
    purchase_id uuid NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event       text NOT NULL,
    detail      jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_purchase_events_purchase ON purchase_events(purchase_id, id);
