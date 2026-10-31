-- Browser agent runs (read-only release: browse, compare, fill a cart; stop at any payment step) and their steps.
CREATE TABLE browse_runs (
  account_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  goal TEXT NOT NULL,
  status TEXT NOT NULL,
  url TEXT,
  answer TEXT,
  reason TEXT,
  pending_json TEXT,
  takeover_until INTEGER,
  jev_asked INTEGER NOT NULL DEFAULT 0,
  jev_agree INTEGER NOT NULL DEFAULT 0,
  estimated_cost_microusd INTEGER NOT NULL DEFAULT 0,
  created_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,request_id),
  FOREIGN KEY(account_id,request_id) REFERENCES customer_requests(account_id,id)
);
CREATE TABLE browse_steps (
  account_id TEXT NOT NULL,
  request_id TEXT NOT NULL,
  n INTEGER NOT NULL,
  kind TEXT NOT NULL,
  data_json TEXT NOT NULL,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,request_id,n),
  FOREIGN KEY(account_id,request_id) REFERENCES browse_runs(account_id,request_id)
);
