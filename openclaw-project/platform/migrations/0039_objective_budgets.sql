-- Long work as a durable objective (roadmap #6, #7): one objective per "keep working until complete" chain, a checkpoint per finished turn, a budget the customer can
-- see, and a resume policy they choose. Additive; `resume_mode` (always 'explicit') stays for older code: it says a HOST RESTART never resumes work by itself, which is
-- still true. `resume_policy` is the customer's own choice of what happens after an interrupted turn: ask them, or carry on within their limits.
ALTER TABLE objectives ADD COLUMN conversation_id TEXT;
ALTER TABLE objectives ADD COLUMN resume_policy TEXT NOT NULL DEFAULT 'ask' CHECK(resume_policy IN ('ask','auto'));
ALTER TABLE objectives ADD COLUMN max_turns INTEGER CHECK(max_turns IS NULL OR max_turns BETWEEN 1 AND 500);
ALTER TABLE objectives ADD COLUMN max_seconds INTEGER CHECK(max_seconds IS NULL OR max_seconds BETWEEN 60 AND 2592000);
ALTER TABLE objectives ADD COLUMN pause_reason TEXT;
ALTER TABLE objectives ADD COLUMN auto_resumes INTEGER NOT NULL DEFAULT 0;
CREATE INDEX objectives_by_task ON objectives(account_id, task_id);
CREATE INDEX objectives_by_conversation ON objectives(account_id, conversation_id, created_epoch);
