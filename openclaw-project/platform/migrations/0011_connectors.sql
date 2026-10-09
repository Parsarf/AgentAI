-- Phase 11: customer-owned connectors, OAuth link state, operations, drafts, browser profiles.
-- Provider tokens are never stored here: only opaque custody references.
CREATE TABLE connector_connections (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  id TEXT NOT NULL,
  service TEXT NOT NULL CHECK(length(service) BETWEEN 1 AND 40),
  state TEXT NOT NULL CHECK(state IN ('connected','reconnect_required','revoked')),
  identity_label TEXT NOT NULL CHECK(length(identity_label) BETWEEN 1 AND 320),
  granted_scopes TEXT NOT NULL CHECK(json_valid(granted_scopes)),
  selected_resources TEXT NOT NULL CHECK(json_valid(selected_resources)),
  secret_ref TEXT,
  created_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL,
  revoked_epoch INTEGER,
  PRIMARY KEY(account_id,id)
);
CREATE INDEX connector_connections_service ON connector_connections(account_id,service,state);
CREATE TABLE connector_link_states (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  state_hash TEXT NOT NULL CHECK(length(state_hash)=64),
  actor_id TEXT NOT NULL,
  service TEXT NOT NULL,
  redirect_uri TEXT NOT NULL,
  verifier_ref TEXT NOT NULL,
  selected_resources TEXT NOT NULL CHECK(json_valid(selected_resources)),
  expires_epoch INTEGER NOT NULL,
  used_epoch INTEGER,
  PRIMARY KEY(state_hash)
);
CREATE TABLE connector_operations (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  connection_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(length(kind) BETWEEN 1 AND 20),
  state TEXT NOT NULL CHECK(state IN ('pending','running','completed','failed','uncertain','cancelled')),
  idempotency_key TEXT NOT NULL,
  request_hash TEXT NOT NULL CHECK(length(request_hash)=64),
  target TEXT NOT NULL DEFAULT '',
  provider_receipt TEXT,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,id),
  UNIQUE(account_id,idempotency_key),
  FOREIGN KEY(account_id,connection_id) REFERENCES connector_connections(account_id,id)
);
CREATE TABLE connector_drafts (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  id TEXT NOT NULL,
  service TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('email','event','repository_change')),
  title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200),
  body TEXT NOT NULL CHECK(length(body) BETWEEN 1 AND 20000),
  state TEXT NOT NULL CHECK(state IN ('proposed','discarded')),
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,id)
);
CREATE TABLE browser_profiles (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  id TEXT NOT NULL,
  label TEXT NOT NULL CHECK(length(label) BETWEEN 1 AND 80),
  allowed_hosts TEXT NOT NULL CHECK(json_valid(allowed_hosts)),
  credential_ref TEXT,
  session_ref TEXT,
  state TEXT NOT NULL CHECK(state IN ('active','revoked')),
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,id),
  UNIQUE(account_id,label)
);
