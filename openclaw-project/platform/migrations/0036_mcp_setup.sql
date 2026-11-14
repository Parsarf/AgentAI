-- Additive: old binaries can still read existing connections after rollback.
ALTER TABLE mcp_connections ADD COLUMN requested_auth TEXT NOT NULL DEFAULT '';
ALTER TABLE mcp_connections ADD COLUMN transport TEXT NOT NULL DEFAULT 'auto';
ALTER TABLE mcp_connections ADD COLUMN added_by TEXT NOT NULL DEFAULT 'you';
ALTER TABLE mcp_connections ADD COLUMN source_url TEXT NOT NULL DEFAULT '';
ALTER TABLE mcp_connections ADD COLUMN setup_confirmed INTEGER NOT NULL DEFAULT 1 CHECK(setup_confirmed IN (0,1));
CREATE INDEX mcp_connections_endpoint ON mcp_connections(account_id,url);
