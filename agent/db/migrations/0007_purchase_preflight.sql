-- Phase 6 provider-independent, tenant-scoped purchase policy and denied-attempt audit.
-- No funding credentials or executable purchases are stored until a merchant
-- payment provider with user authorization and idempotency is selected.
CREATE TABLE purchase_policies (
    user_id uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    opted_in boolean NOT NULL DEFAULT false,
    per_transaction_cap_usd numeric(12,2) NOT NULL DEFAULT 0 CHECK (per_transaction_cap_usd >= 0),
    monthly_cap_usd numeric(12,2) NOT NULL DEFAULT 0 CHECK (monthly_cap_usd >= 0),
    merchant_allowlist text[] NOT NULL DEFAULT '{}',
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE purchase_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id text NOT NULL,
    task_source text NOT NULL,
    merchant text,
    amount_usd numeric(12,2),
    description text,
    outcome text NOT NULL CHECK (outcome IN ('denied', 'invalid')),
    reason text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_purchase_attempts_user_created
    ON purchase_attempts(user_id, created_at DESC);
