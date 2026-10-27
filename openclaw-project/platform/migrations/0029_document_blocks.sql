-- 'document': a composed answer (ordered, validated blocks written by the assistant in a ```lumina-doc fence; see agentai_platform/genui/document.py).
-- SQLite cannot widen a CHECK in place, so the table is rebuilt with the same columns and every existing row is copied over unchanged.
CREATE TABLE data_blocks_new (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  anchor_message_id INTEGER,
  kind TEXT NOT NULL CHECK(kind IN ('table','chart','comparison','places','products','steps','answer','choice','callout','timeline','sources','display','document')),
  spec_json TEXT NOT NULL,
  source_request_id TEXT,
  position INTEGER NOT NULL DEFAULT 0,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,id),
  UNIQUE(account_id,source_request_id,position),
  FOREIGN KEY(account_id,conversation_id) REFERENCES conversations(account_id,id)
);
INSERT INTO data_blocks_new(account_id,id,conversation_id,anchor_message_id,kind,spec_json,source_request_id,position,created_epoch)
  SELECT account_id,id,conversation_id,anchor_message_id,kind,spec_json,source_request_id,position,created_epoch FROM data_blocks;
DROP TABLE data_blocks;
ALTER TABLE data_blocks_new RENAME TO data_blocks;
CREATE INDEX data_blocks_conversation ON data_blocks(account_id,conversation_id,created_epoch);
