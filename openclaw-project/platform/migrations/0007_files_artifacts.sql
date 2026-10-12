-- Phase 8: project files (quarantined until scanned) and download tickets.
CREATE TABLE project_files (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  project_id TEXT NOT NULL,
  id TEXT NOT NULL,
  display_name TEXT NOT NULL,
  media_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL CHECK(size_bytes>0),
  sha256 TEXT NOT NULL CHECK(length(sha256)=64),
  storage_ref TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('quarantined','scanned','rejected')),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  PRIMARY KEY(account_id,id),
  FOREIGN KEY(account_id,project_id) REFERENCES projects(account_id,id)
);
CREATE INDEX project_files_project ON project_files(account_id,project_id,created_at);

-- Short-lived single-use download tickets; only the HMAC is stored.
CREATE TABLE download_tickets (
  ticket_hash TEXT PRIMARY KEY,
  account_id TEXT NOT NULL REFERENCES accounts(id),
  artifact_id TEXT NOT NULL,
  version INTEGER NOT NULL CHECK(version>0),
  expires_epoch INTEGER NOT NULL,
  consumed_epoch INTEGER,
  created_epoch INTEGER NOT NULL
);
