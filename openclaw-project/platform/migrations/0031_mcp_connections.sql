-- Remote MCP credentials are encrypted and account/connection bound; never restored from backups.
CREATE TABLE mcp_connections (
 account_id TEXT NOT NULL REFERENCES accounts(id), id TEXT NOT NULL, name TEXT NOT NULL,
 url TEXT NOT NULL, auth_method TEXT NOT NULL CHECK(auth_method IN ('none','bearer','oauth')),
 enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
 state TEXT NOT NULL DEFAULT 'connecting', error_code TEXT, busy_until INTEGER NOT NULL DEFAULT 0, generation INTEGER NOT NULL DEFAULT 1,
 secret_json TEXT NOT NULL DEFAULT '{}', tools_json TEXT NOT NULL DEFAULT '[]', checked_epoch INTEGER,
 oauth_state_hash TEXT, oauth_actor TEXT, oauth_session TEXT, oauth_browser_hash TEXT, oauth_expires INTEGER,
 created_epoch INTEGER NOT NULL, PRIMARY KEY(account_id,id), UNIQUE(oauth_state_hash)
);
CREATE TABLE mcp_tool_choices (
 account_id TEXT NOT NULL, connection_id TEXT NOT NULL, tool_name TEXT NOT NULL,
 schema_hash TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
 PRIMARY KEY(account_id,connection_id,tool_name),
 FOREIGN KEY(account_id,connection_id) REFERENCES mcp_connections(account_id,id) ON DELETE CASCADE
);
-- Same exact-payload/target/expiry authorization as connector writes, consumed atomically.
-- Remote annotations cannot authorize an action, so every custom tool requires customer approval.
CREATE TABLE mcp_calls (
 account_id TEXT NOT NULL, id TEXT NOT NULL, connection_id TEXT NOT NULL, tool_name TEXT NOT NULL,
 payload_hash TEXT NOT NULL, schema_hash TEXT NOT NULL, request_id TEXT NOT NULL,
 arguments_json TEXT NOT NULL, state TEXT NOT NULL, result_json TEXT,
 expires_epoch INTEGER NOT NULL, created_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,id),
 FOREIGN KEY(account_id,connection_id) REFERENCES mcp_connections(account_id,id) ON DELETE CASCADE
);
CREATE INDEX mcp_calls_lookup ON mcp_calls(account_id,connection_id,tool_name,payload_hash,state);
