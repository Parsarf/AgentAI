-- Owner's own per-tool choice to run a remote MCP tool without asking each time.
-- Never derived from remote annotations. Cleared whenever the tool is disabled or its schema changes.
ALTER TABLE mcp_tool_choices ADD COLUMN auto_approve INTEGER NOT NULL DEFAULT 0 CHECK(auto_approve IN (0,1));
