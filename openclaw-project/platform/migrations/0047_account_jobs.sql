-- Data lifecycle (roadmap #19 export, #20 deletion, #21 offboarding). Additive: an older release ignores all of it.
-- One row per export, deletion or offboarding of an account. It is deliberately NOT tied to the account's other rows by a foreign key: a deletion keeps its checkpoints and
-- its report after every other row of the account is gone. `steps_json` is the list of checkpoints (each store that was handled, with counts, never content), so a job that
-- is interrupted carries on from the last finished step.
CREATE TABLE account_jobs (
 id TEXT PRIMARY KEY, account_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('export','deletion','offboarding')),
 scope_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(scope_json)),
 state TEXT NOT NULL CHECK(state IN ('requested','running','waiting','completed','failed','cancelled','expired')),
 steps_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(steps_json)),
 report_json TEXT CHECK(report_json IS NULL OR json_valid(report_json)),
 archive_ref TEXT, archive_bytes INTEGER, archive_sha256 TEXT, ticket_hash TEXT, ticket_expires_epoch INTEGER,
 not_before_epoch INTEGER, waiting_for TEXT CHECK(waiting_for IS NULL OR length(waiting_for)<=40), child_job_id TEXT,
 lease_until INTEGER NOT NULL DEFAULT 0,
 created_epoch INTEGER NOT NULL, updated_epoch INTEGER NOT NULL, finished_epoch INTEGER
);
CREATE INDEX account_jobs_by_account ON account_jobs(account_id,created_epoch);
CREATE INDEX account_jobs_by_state ON account_jobs(state,updated_epoch);
-- What accounting rules require to be kept after an account is deleted: amounts and dates, with no link to any chat, task or file (those rows are gone).
CREATE TABLE financial_records (
 account_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('provider_receipt','usage_entry')), reference TEXT NOT NULL,
 provider TEXT NOT NULL DEFAULT '', price_version TEXT NOT NULL DEFAULT '', amount_microusd INTEGER NOT NULL, occurred TEXT NOT NULL,
 PRIMARY KEY(account_id,kind,reference)
);
-- A chat the customer deleted. Its content is removed; where files it made are still kept, an empty record of the chat stays so those files still belong somewhere.
ALTER TABLE conversations ADD COLUMN deleted_epoch INTEGER;
