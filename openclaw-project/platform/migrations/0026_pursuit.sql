-- Pursuit foundations (plans/pursuit-architecture.md, phase 1). Nothing reads these tables unless the owner switch `pursuit` is on.
-- pursuit_state: the goal, success criteria, plan and progress of one request, as one bounded JSON document (pursuit.py owns the shape; status mirrors it so it can be listed).
-- Statuses (code-level enum, the column is plain TEXT): planning, running, waiting_user, replanning, verifying, verified, unverified_done, blocked, stopped, cancelled.
CREATE TABLE pursuit_state (
  account_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  state_json TEXT NOT NULL,
  status TEXT NOT NULL,
  created_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,request_id),
  FOREIGN KEY(account_id,request_id) REFERENCES customer_requests(account_id,id)
);
-- browse_sessions: one row per browser job after the first of a request. Session 1 is the request's own job and keeps using browse_runs/browse_steps exactly as before.
-- job_id is the id the browse service knows the job by (32 hex, see browse/sessions.py); n_offset is how many steps of the request were already recorded, so a later
-- session's steps continue the request's numbering in browse_steps.
CREATE TABLE browse_sessions (
  account_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  session INTEGER NOT NULL CHECK(session >= 2),
  job_id TEXT NOT NULL,
  n_offset INTEGER NOT NULL DEFAULT 0,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,request_id,session),
  UNIQUE(account_id,job_id),
  FOREIGN KEY(account_id,request_id) REFERENCES customer_requests(account_id,id)
);
