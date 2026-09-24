-- Phase 5: durable cost identities, budget reservations, and subscription state.
ALTER TABLE api_costs ADD COLUMN operation_key text;
ALTER TABLE tasks ALTER COLUMN cost_usd TYPE numeric(12, 6);
ALTER TABLE usage_periods ALTER COLUMN total_cost TYPE numeric(12, 6);
ALTER TABLE usage_periods ALTER COLUMN included_allowance TYPE numeric(12, 6);
ALTER TABLE usage_periods ALTER COLUMN overage TYPE numeric(12, 6);
CREATE UNIQUE INDEX idx_api_costs_user_operation
    ON api_costs(user_id, operation_key) WHERE operation_key IS NOT NULL;
CREATE INDEX idx_api_costs_time_user ON api_costs(created_at, user_id);

CREATE TABLE budget_reservations (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id uuid,
    operation_key text NOT NULL,
    period_start date NOT NULL,
    amount_usd numeric(12, 6) NOT NULL CHECK (amount_usd > 0),
    state text NOT NULL DEFAULT 'reserved'
        CHECK (state IN ('reserved', 'settled', 'unknown')),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(user_id, operation_key)
);
CREATE INDEX idx_budget_reservations_user_period
    ON budget_reservations(user_id, period_start, state);

ALTER TABLE users ADD COLUMN billing_state text NOT NULL DEFAULT 'none'
    CHECK (billing_state IN ('none', 'active', 'trialing', 'past_due', 'unpaid', 'canceled'));
ALTER TABLE users ADD COLUMN stripe_subscription_id text;
ALTER TABLE users ADD COLUMN billing_grace_until timestamptz;
CREATE UNIQUE INDEX idx_users_stripe_customer
    ON users(stripe_customer_id) WHERE stripe_customer_id IS NOT NULL;
CREATE UNIQUE INDEX idx_users_stripe_subscription
    ON users(stripe_subscription_id) WHERE stripe_subscription_id IS NOT NULL;

CREATE TABLE processed_stripe_events (
    event_id text PRIMARY KEY,
    event_type text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE billing_operations (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind text NOT NULL,
    operation_key text NOT NULL,
    provider_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id, kind, operation_key)
);

CREATE TABLE billing_warnings (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    period_start date NOT NULL,
    threshold integer NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(user_id, period_start, threshold)
);
