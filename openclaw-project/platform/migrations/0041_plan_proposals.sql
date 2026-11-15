-- Plan adaptation (roadmap #11): when a phase fails, an earlier result changes what should come next, or the customer gives a new instruction, the assistant proposes a REVISION
-- of the running plan. It is stored as a difference against the current plan; completed phases are never part of what changes. The customer approves it (or declines it),
-- unless they chose automatic replanning for that plan. Additive.
CREATE TABLE plan_proposals (
 account_id TEXT NOT NULL, block_id TEXT NOT NULL, id TEXT NOT NULL,
 trigger TEXT NOT NULL CHECK(trigger IN ('failure','invalidated','instruction')),
 instruction TEXT NOT NULL DEFAULT '' CHECK(length(instruction)<=2000),
 base_revision INTEGER NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('requested','proposed','applied','declined','superseded','failed')),
 plan_json TEXT CHECK(plan_json IS NULL OR json_valid(plan_json)),
 diff_json TEXT CHECK(diff_json IS NULL OR json_valid(diff_json)),
 summary TEXT NOT NULL DEFAULT '' CHECK(length(summary)<=600),
 request_id TEXT, auto INTEGER NOT NULL DEFAULT 0 CHECK(auto IN (0,1)),
 created_epoch INTEGER NOT NULL, decided_epoch INTEGER,
 PRIMARY KEY(account_id,block_id,id),
 FOREIGN KEY(account_id,block_id) REFERENCES ui_blocks(account_id,id)
);
CREATE INDEX plan_proposals_by_block ON plan_proposals(account_id,block_id,created_epoch);
-- Per plan: did the customer let the assistant revise it by itself when a phase fails, and how many automatic revisions have been used (bounded by the platform).
CREATE TABLE plan_settings (
 account_id TEXT NOT NULL, block_id TEXT NOT NULL,
 auto_replan INTEGER NOT NULL DEFAULT 0 CHECK(auto_replan IN (0,1)),
 auto_used INTEGER NOT NULL DEFAULT 0 CHECK(auto_used>=0),
 updated_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,block_id),
 FOREIGN KEY(account_id,block_id) REFERENCES ui_blocks(account_id,id)
);
