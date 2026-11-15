-- The schedule engine (roadmap #78, #79 engines): a schedule now says what its run does, what happens to a run missed while the host was down, and how long the customer's
-- grant to run unattended lasts. Every firing (and every day that did not fire, with the reason) is one row in schedule_runs: the primary key makes "at most one run per schedule per
-- local day" a property of the database, not of the code, so a restart or a second engine can never fire it twice. Additive.
ALTER TABLE schedules ADD COLUMN prompt TEXT NOT NULL DEFAULT '' CHECK(length(prompt)<=2000);
ALTER TABLE schedules ADD COLUMN missed_policy TEXT NOT NULL DEFAULT 'skip' CHECK(missed_policy IN ('run_once','skip'));
ALTER TABLE schedules ADD COLUMN grace_seconds INTEGER NOT NULL DEFAULT 900 CHECK(grace_seconds BETWEEN 60 AND 86400);
ALTER TABLE schedules ADD COLUMN approved_until_epoch INTEGER;
ALTER TABLE schedules ADD COLUMN conversation_id TEXT;
CREATE TABLE schedule_runs (
 account_id TEXT NOT NULL, schedule_id TEXT NOT NULL, day TEXT NOT NULL CHECK(length(day)=10),
 state TEXT NOT NULL CHECK(state IN ('firing','started','completed','failed','blocked','refused','missed','unchanged','denied')),
 reason TEXT NOT NULL DEFAULT '' CHECK(length(reason)<=40),
 request_id TEXT, created_epoch INTEGER NOT NULL, finished_epoch INTEGER,
 PRIMARY KEY(account_id,schedule_id,day),
 FOREIGN KEY(account_id,schedule_id) REFERENCES schedules(account_id,id)
);
CREATE INDEX schedule_runs_by_state ON schedule_runs(state,created_epoch);
