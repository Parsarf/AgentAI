-- Phase 12: optional TypeSafe optimization gates. Disabled by default at every layer.
CREATE TABLE optimization_activations (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  track TEXT NOT NULL CHECK(track IN ('browser','research')),
  state TEXT NOT NULL CHECK(state IN ('disabled','enabled')),
  data_handling_approved_epoch INTEGER,
  transport_reviewed_epoch INTEGER,
  typesafe_account_ref TEXT,
  updated_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,track)
);
CREATE TABLE optimization_calls (
  account_id TEXT NOT NULL,
  task_id TEXT NOT NULL,
  call_id TEXT NOT NULL,
  track TEXT NOT NULL CHECK(track IN ('browser','research')),
  bound_microusd INTEGER NOT NULL CHECK(bound_microusd>0),
  state TEXT NOT NULL CHECK(state IN ('reserved','recorded','uncertain','reconciled')),
  input_tokens INTEGER,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,call_id),
  FOREIGN KEY(account_id,task_id) REFERENCES tasks(account_id,id)
);
CREATE INDEX optimization_calls_task ON optimization_calls(account_id,task_id,state);
