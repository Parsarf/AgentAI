-- Phase 10: durable objectives with checkpoints, and gated customer schedules.
CREATE TABLE objectives (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  project_id TEXT NOT NULL,
  id TEXT NOT NULL,
  task_id TEXT,
  native_goal_ref TEXT,
  native_state TEXT NOT NULL DEFAULT 'unknown',
  app_state TEXT NOT NULL CHECK(app_state IN ('active','paused','needs_reconciliation','cancelled','completed','failed')),
  resume_mode TEXT NOT NULL DEFAULT 'explicit' CHECK(resume_mode='explicit'),
  cancelled INTEGER NOT NULL DEFAULT 0 CHECK(cancelled IN (0,1)),
  created_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,id),
  FOREIGN KEY(account_id,project_id) REFERENCES projects(account_id,id)
);
CREATE TABLE objective_checkpoints (
  account_id TEXT NOT NULL,
  objective_id TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK(sequence>0),
  step TEXT NOT NULL CHECK(length(step) BETWEEN 1 AND 200),
  receipt_id TEXT,
  effect_state TEXT NOT NULL CHECK(effect_state IN ('none','confirmed','uncertain','reconciled')),
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,objective_id,sequence),
  UNIQUE(account_id,objective_id,receipt_id),
  FOREIGN KEY(account_id,objective_id) REFERENCES objectives(account_id,id)
);
CREATE TABLE objective_children (
  account_id TEXT NOT NULL,
  objective_id TEXT NOT NULL,
  child_ref TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('subagent','job','schedule')),
  state TEXT NOT NULL CHECK(state IN ('active','cancelled','finished')),
  PRIMARY KEY(account_id,objective_id,child_ref),
  FOREIGN KEY(account_id,objective_id) REFERENCES objectives(account_id,id)
);
CREATE TABLE schedules (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  project_id TEXT NOT NULL,
  id TEXT NOT NULL,
  name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
  timezone TEXT NOT NULL,
  hour_local INTEGER NOT NULL CHECK(hour_local BETWEEN 0 AND 23),
  minute_local INTEGER NOT NULL CHECK(minute_local BETWEEN 0 AND 59),
  timeout_seconds INTEGER NOT NULL CHECK(timeout_seconds BETWEEN 30 AND 900),
  task_budget_microusd INTEGER NOT NULL CHECK(task_budget_microusd>=0),
  watcher_id TEXT,
  state TEXT NOT NULL CHECK(state IN ('active','paused')),
  last_fired_day TEXT,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,id),
  UNIQUE(account_id,project_id,name),
  FOREIGN KEY(account_id,project_id) REFERENCES projects(account_id,id)
);
