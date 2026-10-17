-- Task control (Lumina phase 4): a waiting task can be paused (held in the queue: never claimed, never wakes the assistant), and a retry points at the task it re-runs.
ALTER TABLE customer_requests ADD COLUMN paused INTEGER NOT NULL DEFAULT 0 CHECK(paused IN (0,1));
ALTER TABLE customer_requests ADD COLUMN retry_of TEXT;
