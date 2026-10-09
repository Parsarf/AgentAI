-- Phase 10: tenant-scoped memory, reusable skills and watchers.
CREATE TABLE memory_entries (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  project_id TEXT NOT NULL,
  id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('preference','fact','correction','reference')),
  content TEXT NOT NULL CHECK(length(content)<=2000),
  source TEXT NOT NULL CHECK(source IN ('customer','agent','outside')),
  source_ref TEXT NOT NULL DEFAULT '',
  confidence TEXT NOT NULL CHECK(confidence IN ('low','medium','high')),
  last_confirmed_epoch INTEGER NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('active','superseded','deleted')),
  supersedes_id TEXT,
  created_epoch INTEGER NOT NULL,
  deleted_epoch INTEGER,
  PRIMARY KEY(account_id,id),
  FOREIGN KEY(account_id,project_id) REFERENCES projects(account_id,id)
);
CREATE INDEX memory_active ON memory_entries(account_id,project_id,status);
CREATE TABLE memory_terms (
  account_id TEXT NOT NULL,
  entry_id TEXT NOT NULL,
  term TEXT NOT NULL,
  PRIMARY KEY(account_id,entry_id,term),
  FOREIGN KEY(account_id,entry_id) REFERENCES memory_entries(account_id,id)
);
CREATE INDEX memory_terms_lookup ON memory_terms(account_id,term);
CREATE TABLE skills (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  id TEXT NOT NULL,
  name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,id),
  UNIQUE(account_id,name)
);
CREATE TABLE skill_versions (
  account_id TEXT NOT NULL,
  skill_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version>0),
  body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 20000),
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  status TEXT NOT NULL CHECK(status IN ('active','proposed','rejected','superseded')),
  proposed_by TEXT NOT NULL,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,skill_id,version),
  FOREIGN KEY(account_id,skill_id) REFERENCES skills(account_id,id)
);
CREATE TABLE watchers (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  project_id TEXT NOT NULL,
  id TEXT NOT NULL,
  name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80),
  check_spec TEXT NOT NULL CHECK(json_valid(check_spec)),
  interval_seconds INTEGER NOT NULL CHECK(interval_seconds>=300),
  state TEXT NOT NULL CHECK(state IN ('active','paused')),
  last_observed_hash TEXT,
  last_checked_epoch INTEGER,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,id),
  UNIQUE(account_id,project_id,name),
  FOREIGN KEY(account_id,project_id) REFERENCES projects(account_id,id)
);
CREATE TABLE watcher_notifications (
  account_id TEXT NOT NULL,
  watcher_id TEXT NOT NULL,
  observed_hash TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('pending','delivered','denied')),
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,watcher_id,observed_hash),
  FOREIGN KEY(account_id,watcher_id) REFERENCES watchers(account_id,id)
);
