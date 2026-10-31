-- A launched plan runs phase by phase: each enabled phase is its own request, so progress, approval gates and edits to
-- future phases are real. Conversations can be renamed.
CREATE TABLE plan_phase_runs (
  account_id TEXT NOT NULL,
  block_id TEXT NOT NULL,
  phase_id TEXT NOT NULL,
  position INTEGER NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('pending','running','awaiting_approval','completed','failed','skipped','cancelled')),
  attempts INTEGER NOT NULL DEFAULT 0,
  request_id TEXT,
  summary TEXT,
  approved_epoch INTEGER,
  started_epoch INTEGER,
  finished_epoch INTEGER,
  PRIMARY KEY(account_id,block_id,phase_id),
  FOREIGN KEY(account_id,block_id) REFERENCES ui_blocks(account_id,id)
);
ALTER TABLE conversations ADD COLUMN title TEXT;
ALTER TABLE ui_blocks ADD COLUMN actor_id TEXT;   -- who launched the plan: phase requests are admitted as them
