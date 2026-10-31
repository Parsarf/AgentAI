-- Generative UI blocks (validated specifications, never code), plan revisions and plan launches.
ALTER TABLE customer_requests ADD COLUMN intent TEXT NOT NULL DEFAULT 'chat';
ALTER TABLE customer_requests ADD COLUMN context_json TEXT;

CREATE TABLE ui_blocks (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  id TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  anchor_message_id INTEGER,
  kind TEXT NOT NULL CHECK(kind IN ('form','task_plan')),
  schema_version TEXT NOT NULL,
  spec_json TEXT NOT NULL,
  state_json TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1 CHECK(version>0),
  status TEXT NOT NULL CHECK(status IN ('draft','submitted','launched','superseded')),
  source_request_id TEXT,
  launched_request_id TEXT,
  idempotency_key TEXT NOT NULL,
  created_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,id),
  UNIQUE(account_id,idempotency_key),
  FOREIGN KEY(account_id,conversation_id) REFERENCES conversations(account_id,id)
);
CREATE INDEX ui_blocks_conversation ON ui_blocks(account_id,conversation_id,created_epoch);

CREATE TABLE plan_revisions (
  account_id TEXT NOT NULL,
  block_id TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK(revision>0),
  source TEXT NOT NULL CHECK(source IN ('ai','user','approved')),
  plan_json TEXT NOT NULL,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,block_id,revision),
  FOREIGN KEY(account_id,block_id) REFERENCES ui_blocks(account_id,id)
);

CREATE TABLE plan_launches (
  account_id TEXT NOT NULL,
  block_id TEXT NOT NULL,
  revision INTEGER NOT NULL,
  request_id TEXT NOT NULL,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,block_id,revision),
  FOREIGN KEY(account_id,block_id,revision) REFERENCES plan_revisions(account_id,block_id,revision)
);
