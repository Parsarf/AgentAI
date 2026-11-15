-- Parallel phases of one plan (roadmap #10) and the exact accounting they need.
-- A phase that can run beside another runs in a LANE: a hidden child conversation of the plan's conversation, with its own runtime session. `parent_id` marks it (NULL for an ordinary
-- conversation); `plan_phase_runs.conversation_id` says where each phase of a plan runs.
ALTER TABLE conversations ADD COLUMN parent_id TEXT;
ALTER TABLE plan_phase_runs ADD COLUMN conversation_id TEXT;
CREATE INDEX conversations_by_parent ON conversations(account_id,parent_id);
-- Spend marks: what the cell's model key had spent in total at the moment a request started and ended. The key's total is one number for the whole cell, so when two requests of one
-- account run at the same time each one's cost is the key's spend between its marks, split equally between the requests running in each stretch (spend_share.py). Alone, a request's cost
-- is simply its end minus its start, as before.
CREATE TABLE spend_marks (
 account_id TEXT NOT NULL, id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('start','end')), spend_microusd INTEGER NOT NULL CHECK(spend_microusd>=0), epoch INTEGER NOT NULL,
 UNIQUE(account_id,request_id,kind)
);
CREATE INDEX spend_marks_by_account ON spend_marks(account_id,epoch);
