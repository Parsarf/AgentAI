-- Phase 6: customer chat transcript and native delivery metadata.
-- The conversation binding on a chat request is enforced by admission
-- (BudgetLedger.admit rechecks account/project/conversation ownership inside
-- its own transaction); SQLite cannot add a composite foreign key column here.
ALTER TABLE customer_requests ADD COLUMN conversation_id TEXT;

CREATE TABLE chat_messages (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  conversation_id TEXT NOT NULL,
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT,
  provenance TEXT NOT NULL CHECK(provenance IN ('customer','agent','system')),
  content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 16000),
  native_message_id TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(account_id, conversation_id, native_message_id),
  FOREIGN KEY(account_id, conversation_id) REFERENCES conversations(account_id, id)
);
CREATE INDEX chat_messages_conversation ON chat_messages(account_id, conversation_id, id);

CREATE TABLE chat_deliveries (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  request_id TEXT NOT NULL,
  attempt INTEGER NOT NULL CHECK(attempt>0),
  idempotency_key TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('pending','acknowledged','uncertain','aborted','failed')),
  native_operation_id TEXT,
  native_run_id TEXT,
  ack_message_seq INTEGER,
  created_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id, request_id, attempt),
  UNIQUE(account_id, idempotency_key, attempt),
  FOREIGN KEY(account_id, request_id) REFERENCES customer_requests(account_id, id)
);
