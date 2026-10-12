-- Phase 7: one Telegram ingress with secure account linking.
-- chat_messages is rebuilt to add the 'telegram' provenance; rows are copied.
CREATE TABLE chat_messages_v6 (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  conversation_id TEXT NOT NULL,
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT,
  provenance TEXT NOT NULL CHECK(provenance IN ('customer','agent','system','telegram')),
  content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 16000),
  native_message_id TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  UNIQUE(account_id, conversation_id, native_message_id),
  FOREIGN KEY(account_id, conversation_id) REFERENCES conversations(account_id, id)
);
INSERT INTO chat_messages_v6(account_id,conversation_id,id,request_id,provenance,content,native_message_id,created_at)
  SELECT account_id,conversation_id,id,request_id,provenance,content,native_message_id,created_at FROM chat_messages;
DROP TABLE chat_messages;
ALTER TABLE chat_messages_v6 RENAME TO chat_messages;
CREATE INDEX chat_messages_conversation ON chat_messages(account_id, conversation_id, id);

-- One numeric Telegram identity maps to at most one account; an account may hold
-- several linked chats. Validity is rechecked against live account/membership
-- state on every use, so suspension and revocation take effect immediately.
CREATE TABLE telegram_links (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  chat_id TEXT NOT NULL,
  telegram_user_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  selected_project_id TEXT,
  created_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id, chat_id),
  UNIQUE(chat_id),
  FOREIGN KEY(account_id, selected_project_id) REFERENCES projects(account_id, id)
);

-- Bearer link codes: only the SHA-256 hash is stored, single use, short expiry.
CREATE TABLE telegram_link_codes (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  id TEXT NOT NULL,
  code_hash TEXT NOT NULL,
  epoch INTEGER NOT NULL,
  expires_epoch INTEGER NOT NULL,
  consumed_epoch INTEGER,
  created_epoch INTEGER NOT NULL,
  actor_id TEXT NOT NULL,
  PRIMARY KEY(account_id, id)
);
CREATE INDEX telegram_link_codes_hash ON telegram_link_codes(code_hash);

-- Durable update deduplication before any routing decision.
CREATE TABLE telegram_updates (
  update_id INTEGER PRIMARY KEY,
  received_epoch INTEGER NOT NULL
);

-- Replies with receipt reconciliation; unknown outcomes stay reconcilable.
CREATE TABLE telegram_outbox (
  account_id TEXT,
  id TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  text TEXT NOT NULL CHECK(length(text) BETWEEN 1 AND 4000),
  state TEXT NOT NULL CHECK(state IN ('pending','sent','uncertain','failed')),
  native_message_id TEXT,
  created_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id, id),
  FOREIGN KEY(account_id) REFERENCES accounts(id)
);
CREATE INDEX telegram_outbox_pending ON telegram_outbox(state, created_epoch);
