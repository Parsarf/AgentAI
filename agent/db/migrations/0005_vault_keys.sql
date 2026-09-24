-- 0005_vault_keys.sql — Phase 4: per-user vault data keys (envelope
-- encryption) and the per-user vault backend mode.
-- NOTE: the phase prompt named this "0004_vault_keys.sql", but 0004 is
-- already taken by Phase 3's users.timezone migration — numbering continues
-- at 0005 (migrations dir is the source of truth).

CREATE TABLE vault_keys (
    user_id     uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    wrapped_key bytea NOT NULL,             -- user's data key, AES-256-GCM-wrapped under the root key
    created_at  timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS vault_mode text NOT NULL DEFAULT 'builtin';
