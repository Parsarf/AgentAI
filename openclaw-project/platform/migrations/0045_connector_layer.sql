-- The connector layer (roadmap #13 resource grants, #16 refresh, #17 revocation, #22 custody, #24 freshness). Additive: an older release ignores all of it.
-- A grant says what one connection may reach: a kind of resource (calendar, folder, label, repository, project ...) and one resource, or '*' when the customer chose "everything".
-- A new connection has no grants, so it can reach nothing until its customer picks.
CREATE TABLE connector_grants (
 account_id TEXT NOT NULL, connection_id TEXT NOT NULL,
 resource_kind TEXT NOT NULL CHECK(length(resource_kind) BETWEEN 1 AND 40), resource_id TEXT NOT NULL CHECK(length(resource_id) BETWEEN 1 AND 300),
 resource_name TEXT NOT NULL DEFAULT '' CHECK(length(resource_name)<=200),
 access TEXT NOT NULL CHECK(access IN ('read','write')), granted_by TEXT NOT NULL, granted_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,connection_id,resource_kind,resource_id),
 FOREIGN KEY(account_id,connection_id) REFERENCES connector_connections(account_id,id)
);
-- Refresh (#16): when the access token ends, when to try next, a lock so two workers never refresh one connection at once, and why a connection needs its customer.
ALTER TABLE connector_connections ADD COLUMN expires_epoch INTEGER;
ALTER TABLE connector_connections ADD COLUMN refresh_after_epoch INTEGER;
ALTER TABLE connector_connections ADD COLUMN refresh_lock_epoch INTEGER;
ALTER TABLE connector_connections ADD COLUMN refresh_failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE connector_connections ADD COLUMN needs_reason TEXT CHECK(needs_reason IS NULL OR length(needs_reason)<=40);
ALTER TABLE connector_connections ADD COLUMN needs_notified_epoch INTEGER;
ALTER TABLE connector_connections ADD COLUMN last_used_epoch INTEGER;
-- A connector that is reached through a remote MCP server (an "MCP wrapper") points at that connection; its credentials stay in the MCP store.
ALTER TABLE connector_connections ADD COLUMN mcp_connection_id TEXT;
-- Custody (#22): provider tokens, sealed (AES-256-GCM, a key per account derived from a master key in a root-only file, bound to the account and the reference). The rows other
-- tables and views read hold only the opaque reference. Never restored from a backup and never exported.
CREATE TABLE connector_secrets (
 account_id TEXT NOT NULL, ref TEXT NOT NULL, label TEXT NOT NULL CHECK(length(label)<=40),
 kid TEXT NOT NULL, nonce BLOB NOT NULL, ciphertext BLOB NOT NULL, created_epoch INTEGER NOT NULL,
 PRIMARY KEY(ref)
);
CREATE INDEX connector_secrets_by_account ON connector_secrets(account_id);
-- Revocation (#17): one audited operation with a receipt of what was stopped (counts and ids, never content).
CREATE TABLE connector_revocations (
 account_id TEXT NOT NULL, id TEXT NOT NULL, connection_id TEXT NOT NULL,
 source TEXT NOT NULL CHECK(source IN ('customer','admin','policy','provider','offboarding')),
 stopped_json TEXT NOT NULL CHECK(json_valid(stopped_json)), created_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,id)
);
-- Freshness (#24): per connection and resource, when it was last read, last read completely, how much it covered, and the last error (a fixed word).
CREATE TABLE connector_freshness (
 account_id TEXT NOT NULL, connection_id TEXT NOT NULL, resource_kind TEXT NOT NULL, resource_id TEXT NOT NULL,
 last_read_epoch INTEGER, last_full_sync_epoch INTEGER, item_count INTEGER, coverage_json TEXT CHECK(coverage_json IS NULL OR json_valid(coverage_json)),
 last_error TEXT CHECK(last_error IS NULL OR length(last_error)<=40), last_error_epoch INTEGER,
 PRIMARY KEY(account_id,connection_id,resource_kind,resource_id)
);
-- A schedule that depends on a connection says so, so removing the connection pauses it with the reason.
ALTER TABLE schedules ADD COLUMN needs_connection_id TEXT;
ALTER TABLE schedules ADD COLUMN pause_reason TEXT CHECK(pause_reason IS NULL OR length(pause_reason)<=80);
