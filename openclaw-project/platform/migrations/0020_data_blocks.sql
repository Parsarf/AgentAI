-- Read-only data cards (table, chart, comparison) attached to assistant answers.
CREATE TABLE data_blocks (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  anchor_message_id INTEGER,
  kind TEXT NOT NULL CHECK(kind IN ('table','chart','comparison')),
  spec_json TEXT NOT NULL,
  source_request_id TEXT,
  position INTEGER NOT NULL DEFAULT 0,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,id),
  UNIQUE(account_id,source_request_id,position),
  FOREIGN KEY(account_id,conversation_id) REFERENCES conversations(account_id,id)
);
CREATE INDEX data_blocks_conversation ON data_blocks(account_id,conversation_id,created_epoch);
