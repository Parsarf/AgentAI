-- Spending limits are the customer's own choice (Settings > Usage). No row, or a NULL column, means no limit.
-- The row under account '*' is the default for every account that has not set its own (only the owner sets it).
-- Additive: old binaries ignore the table.
CREATE TABLE spend_limits (
 account_id TEXT PRIMARY KEY,
 task_microusd INTEGER CHECK(task_microusd IS NULL OR task_microusd>0),
 daily_microusd INTEGER CHECK(daily_microusd IS NULL OR daily_microusd>0),
 period_microusd INTEGER CHECK(period_microusd IS NULL OR period_microusd>0),
 updated_epoch INTEGER NOT NULL
);
