-- 0001_init.sql — Phase 1: all persistent state, tenant-scoped from the ground up.
-- Migrations in db/migrations/ are the source of truth; db/schema.sql is only
-- a generated convenience dump.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE users (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email             citext NOT NULL UNIQUE,
    password_hash     text,
    oauth_subject     text UNIQUE,
    created_at        timestamptz NOT NULL DEFAULT now(),
    plan_tier         text NOT NULL DEFAULT 'free',
    stripe_customer_id text,
    status            text NOT NULL DEFAULT 'email_unverified'
                      CHECK (status IN ('email_unverified', 'active', 'suspended', 'deleted')),
    CONSTRAINT users_auth_present CHECK (password_hash IS NOT NULL OR oauth_subject IS NOT NULL)
);

-- Single-purpose, single-use tokens for email verification / password reset.
CREATE TABLE auth_tokens (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('verify_email', 'password_reset')),
    jti         text NOT NULL UNIQUE,
    expires_at  timestamptz NOT NULL,
    used_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_auth_tokens_user ON auth_tokens(user_id);

CREATE TABLE sessions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  text NOT NULL UNIQUE,          -- sha256 of the opaque token; raw token never stored
    expires_at  timestamptz NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_expires ON sessions(expires_at);

CREATE TABLE telegram_links (
    telegram_chat_id text PRIMARY KEY,
    user_id          uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    linked_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_telegram_links_user ON telegram_links(user_id);

CREATE TABLE tasks (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request        text NOT NULL,
    status         text NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'running', 'awaiting_approval', 'done', 'failed', 'cancelled')),
    source         text NOT NULL CHECK (source IN ('user', 'job')),
    parent_job_id  uuid,
    steps_json     jsonb NOT NULL DEFAULT '[]',
    result         text,
    cost_usd       numeric(12, 4) NOT NULL DEFAULT 0,
    created_at     timestamptz NOT NULL DEFAULT now(),
    started_at     timestamptz,
    finished_at    timestamptz
);
CREATE INDEX idx_tasks_user_status ON tasks(user_id, status);

CREATE TABLE memories (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content      text NOT NULL,
    category     text NOT NULL DEFAULT 'general',
    embedding    vector(384),
    importance   real NOT NULL DEFAULT 0.5,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz
);
CREATE INDEX idx_memories_user ON memories(user_id);
CREATE INDEX idx_memories_embedding ON memories USING hnsw (embedding vector_cosine_ops);

CREATE TABLE jobs (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind              text NOT NULL CHECK (kind IN ('recurring', 'watcher')),
    schedule          text NOT NULL,            -- cron string, evaluated in the user's timezone (Phase 3)
    check_mode        text NOT NULL DEFAULT 'always' CHECK (check_mode IN ('always', 'on_change')),
    check_script_path text,
    instruction       text NOT NULL,
    state_json        jsonb NOT NULL DEFAULT '{}',
    last_run_at       timestamptz,
    next_run_at       timestamptz,
    active            boolean NOT NULL DEFAULT true,
    created_by_task   uuid,
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_jobs_due ON jobs(active, next_run_at);
CREATE INDEX idx_jobs_user ON jobs(user_id);

CREATE TABLE approvals (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id        uuid,
    action_summary text NOT NULL,
    details_json   jsonb NOT NULL DEFAULT '{}',
    status         text NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'approved', 'denied', 'expired')),
    created_at     timestamptz NOT NULL DEFAULT now(),
    decided_at     timestamptz
);
CREATE INDEX idx_approvals_user_status ON approvals(user_id, status);

-- Agent-directed spending ONLY (Phase 6). Platform billing lives in
-- api_costs / usage_periods — the two kinds of money never mix here either.
CREATE TABLE spend_log (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    merchant    text NOT NULL,
    amount      numeric(12, 2) NOT NULL,
    currency    text NOT NULL DEFAULT 'usd',
    approved_by text NOT NULL,                  -- "auto" | deciding user id | "denied" | "timeout"
    status      text NOT NULL,                  -- completed | declined | timeout | ...
    task_id     uuid,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_spend_user_time ON spend_log(user_id, created_at);

CREATE TABLE skills_meta (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name         text NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    uses         integer NOT NULL DEFAULT 0,
    successes    integer NOT NULL DEFAULT 0,
    failures     integer NOT NULL DEFAULT 0,
    reviewed     boolean NOT NULL DEFAULT true,
    last_used_at timestamptz,
    UNIQUE (user_id, name)
);

CREATE TABLE api_costs (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    task_id       uuid,
    model         text NOT NULL,
    input_tokens  integer NOT NULL DEFAULT 0,
    output_tokens integer NOT NULL DEFAULT 0,
    cost_usd      numeric(12, 6) NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_api_costs_user_time ON api_costs(user_id, created_at);

CREATE TABLE usage_periods (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    period_start       date NOT NULL,
    period_end         date NOT NULL,
    total_cost         numeric(12, 4) NOT NULL DEFAULT 0,
    included_allowance numeric(12, 4) NOT NULL DEFAULT 0,
    overage            numeric(12, 4) NOT NULL DEFAULT 0,
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, period_start)
);

CREATE TABLE vault_entries (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    site           text NOT NULL,
    encrypted_blob bytea NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, site)
);
