-- Phase 9: bounded live event streams (max three open per account).
CREATE TABLE event_streams (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  task_id TEXT NOT NULL,
  stream_id TEXT NOT NULL,
  opened_epoch INTEGER NOT NULL,
  expires_epoch INTEGER NOT NULL,
  closed_epoch INTEGER,
  PRIMARY KEY(account_id, stream_id)
);
CREATE INDEX event_streams_active ON event_streams(account_id, closed_epoch, expires_epoch);
