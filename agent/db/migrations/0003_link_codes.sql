-- 0003_link_codes.sql — Phase 2: short-lived, single-use codes linking a
-- Telegram chat to a web account. Only the SHA-256 hash is stored.

CREATE TABLE link_codes (
    code_hash  text PRIMARY KEY,
    user_id    uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL,
    used_at    timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_link_codes_user ON link_codes(user_id);
