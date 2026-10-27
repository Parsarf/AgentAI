-- Native execution: OpenClaw owns the run; Lumina admits it, supervises it and records what happened (docs/architecture/native-execution.md).
--
-- customer_requests
--   outcome / outcome_note / verification: how the task ended, kept apart from whether the run finished. state says the run is over; outcome says what that means for the
--     customer (completed, partial, blocked, failed, cancelled); verification says whether anything Lumina can check supports "done" (verified, unverified, not_applicable).
--   parked_reason / parked_epoch: the run is waiting for a person (a browser question or a hand-off). A parked request keeps its reservation and its cell but holds no
--     slot in request_slot, so one person's slow answer never stops everyone else's work.
--   continues: "Keep working until complete" runs as a chain of requests, one per native turn, each admitted and funded on its own; this names the one before.
--   goal_mode: the customer asked for a session goal on this message.
--   continue_goal: set when the turn ended with the goal still active and the chain may go on; the goal chain admits the next turn once (see goals.py).
--   closing: set in the same transaction that finds no native run still owed to this request; after it, a steer is refused instead of starting an unowned run.
ALTER TABLE customer_requests ADD COLUMN outcome TEXT CHECK(outcome IN ('completed','partial','blocked','failed','cancelled'));
ALTER TABLE customer_requests ADD COLUMN outcome_note TEXT;
ALTER TABLE customer_requests ADD COLUMN verification TEXT CHECK(verification IN ('verified','unverified','not_applicable'));
ALTER TABLE customer_requests ADD COLUMN parked_reason TEXT;
ALTER TABLE customer_requests ADD COLUMN parked_epoch INTEGER;
ALTER TABLE customer_requests ADD COLUMN continues TEXT;
ALTER TABLE customer_requests ADD COLUMN goal_mode INTEGER NOT NULL DEFAULT 0 CHECK(goal_mode IN (0,1));
ALTER TABLE customer_requests ADD COLUMN continue_goal INTEGER NOT NULL DEFAULT 0 CHECK(continue_goal IN (0,1));
ALTER TABLE customer_requests ADD COLUMN closing INTEGER NOT NULL DEFAULT 0 CHECK(closing IN (0,1));

-- Outcomes of requests that finished before this migration: the old states map one to one.
UPDATE customer_requests SET outcome=state WHERE state IN ('completed','failed','cancelled');

-- chat_deliveries: one row per input handed to the runtime (the first turn, a steer, a goal start, a resume). The idempotency key is the native run id.
-- Rebuilt because the state check had to grow ('completed') and every run needs its kind, deadline and end.
CREATE TABLE chat_deliveries_native (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  request_id TEXT NOT NULL,
  attempt INTEGER NOT NULL CHECK(attempt>0),
  idempotency_key TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('pending','acknowledged','uncertain','aborted','failed','completed')),
  native_operation_id TEXT,
  native_run_id TEXT,
  ack_message_seq INTEGER,
  created_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL,
  usage_before_microusd INTEGER,
  kind TEXT NOT NULL DEFAULT 'turn' CHECK(kind IN ('turn','steer','goal_start','goal_resume','goal_continue')),
  goal_issued_ms INTEGER,
  deadline_epoch INTEGER,
  ended_epoch INTEGER,
  native_status TEXT,
  tools_json TEXT,
  payload TEXT,
  PRIMARY KEY(account_id, request_id, attempt),
  UNIQUE(account_id, idempotency_key, attempt),
  FOREIGN KEY(account_id, request_id) REFERENCES customer_requests(account_id, id)
);
INSERT INTO chat_deliveries_native(account_id,request_id,attempt,idempotency_key,payload_hash,state,native_operation_id,native_run_id,ack_message_seq,created_epoch,updated_epoch,usage_before_microusd)
  SELECT account_id,request_id,attempt,idempotency_key,payload_hash,state,native_operation_id,native_run_id,ack_message_seq,created_epoch,updated_epoch,usage_before_microusd FROM chat_deliveries;
DROP TABLE chat_deliveries;
ALTER TABLE chat_deliveries_native RENAME TO chat_deliveries;
CREATE INDEX chat_deliveries_run ON chat_deliveries(account_id, native_run_id);

-- Pursuit (a second planning loop beside the assistant's) is gone; its stored plans were advisory state that nothing else read.
DROP TABLE pursuit_state;
