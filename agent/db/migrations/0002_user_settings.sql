-- 0002_user_settings.sql — Phase 2: per-user approval-rule overrides and
-- general per-user settings (quiet hours etc.), both plan-floored in code.

ALTER TABLE users ADD COLUMN IF NOT EXISTS user_limits_json jsonb;
ALTER TABLE users ADD COLUMN IF NOT EXISTS settings_json jsonb NOT NULL DEFAULT '{}';
