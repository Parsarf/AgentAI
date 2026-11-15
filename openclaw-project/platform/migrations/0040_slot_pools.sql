-- Parallel execution (roadmap #8): the single running slot and the single cell slot become pools.
-- `request_slots`: one row per request that is running right now (an account holds one interactive slot; background slots are for plan phases and schedules).
-- `cell_slots`: one row per customer cell that is running or being started, with the host it runs on (one host today; a second host is a new `host_id`, not a new design).
-- The old `request_slot` and `lifecycle_slot` tables stay, unused, for one release so an older release can still open this database. Rolling back while two
-- cells run at once is not safe: stop the extra cells first (see PENDING_DEPLOY.md of the release that added this).
CREATE TABLE request_slots (
 account_id TEXT NOT NULL, request_id TEXT NOT NULL,
 kind TEXT NOT NULL DEFAULT 'interactive' CHECK(kind IN ('interactive','background')),
 claimed_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,request_id),
 FOREIGN KEY(account_id,request_id) REFERENCES customer_requests(account_id,id)
);
CREATE INDEX request_slots_by_kind ON request_slots(account_id,kind);
CREATE TABLE cell_slots (
 account_id TEXT PRIMARY KEY, deployment_id TEXT NOT NULL, operation_id TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('reserved','active','uncertain')),
 host_id TEXT NOT NULL DEFAULT 'host-1',
 FOREIGN KEY(account_id,deployment_id) REFERENCES deployments(account_id,id),
 FOREIGN KEY(account_id,operation_id) REFERENCES operations(account_id,id)
);
CREATE INDEX cell_slots_by_host ON cell_slots(host_id,state);
-- When a request was last given a slot: the fair order across accounts is "the account served longest ago goes first".
ALTER TABLE customer_requests ADD COLUMN claimed_epoch INTEGER;
INSERT INTO request_slots(account_id,request_id,kind,claimed_epoch) SELECT account_id,request_id,'interactive',CAST(strftime('%s','now') AS INTEGER) FROM request_slot;
INSERT INTO cell_slots(account_id,deployment_id,operation_id,state) SELECT account_id,deployment_id,operation_id,state FROM lifecycle_slot;
