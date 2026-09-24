-- 0004_scheduling_timezone.sql — Phase 3: per-user timezone so cron schedules
-- are evaluated in each user's own local time (core/scheduler_service.py).
-- The jobs and skills_meta tables already exist since 0001.

ALTER TABLE users ADD COLUMN IF NOT EXISTS timezone text NOT NULL DEFAULT 'UTC';
