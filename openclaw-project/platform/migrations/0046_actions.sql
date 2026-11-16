-- The action pipeline (roadmap #26 previews and approval, #83 handoff, #27 undo, #28 compensation, #29 workflows). Additive: an older release ignores these tables.
-- An action is one proposed change in an outside system. It holds the exact payload that will be sent and a hash of it; an approval is for that hash and nothing else.
CREATE TABLE actions (
 account_id TEXT NOT NULL REFERENCES accounts(id), id TEXT NOT NULL,
 request_id TEXT, step INTEGER NOT NULL DEFAULT 1, idempotency_key TEXT NOT NULL, actor_id TEXT NOT NULL,
 connection_id TEXT NOT NULL, provider TEXT NOT NULL, kind TEXT NOT NULL CHECK(length(kind) BETWEEN 1 AND 40),
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), payload_hash TEXT NOT NULL CHECK(length(payload_hash)=64),
 preview_json TEXT NOT NULL CHECK(json_valid(preview_json)),
 target_json TEXT CHECK(target_json IS NULL OR json_valid(target_json)), base_version TEXT,
 before_json TEXT CHECK(before_json IS NULL OR json_valid(before_json)),
 can_undo INTEGER NOT NULL DEFAULT 0 CHECK(can_undo IN (0,1)), undo_kind TEXT, undo_payload_json TEXT CHECK(undo_payload_json IS NULL OR json_valid(undo_payload_json)),
 compensation_json TEXT CHECK(compensation_json IS NULL OR json_valid(compensation_json)),
 undo_of TEXT, compensates TEXT,
 state TEXT NOT NULL CHECK(state IN ('proposed','approved','executing','done','failed','uncertain','undone','compensated','expired','declined')),
 needs_admin INTEGER NOT NULL DEFAULT 0 CHECK(needs_admin IN (0,1)), approved_by TEXT, admin_approved_by TEXT, approved_epoch INTEGER, approval_expires_epoch INTEGER,
 auto_approved INTEGER NOT NULL DEFAULT 0 CHECK(auto_approved IN (0,1)),
 operation_id TEXT, receipt TEXT, result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
 verified INTEGER CHECK(verified IS NULL OR verified IN (0,1)), verify_note TEXT,
 conflict_json TEXT CHECK(conflict_json IS NULL OR json_valid(conflict_json)),
 attempts INTEGER NOT NULL DEFAULT 0, retry_after_epoch INTEGER,
 workflow_id TEXT, workflow_position INTEGER, ended_reason TEXT CHECK(ended_reason IS NULL OR length(ended_reason)<=60),
 created_epoch INTEGER NOT NULL, updated_epoch INTEGER NOT NULL, executed_epoch INTEGER, undo_until_epoch INTEGER,
 PRIMARY KEY(account_id,id), UNIQUE(account_id,idempotency_key)
);
CREATE INDEX actions_by_state ON actions(state,updated_epoch);
CREATE INDEX actions_by_request ON actions(account_id,request_id);
CREATE INDEX actions_by_workflow ON actions(account_id,workflow_id,workflow_position);
-- The customer may let one kind of change on one connection go ahead without asking each time. Never the default; a kind that cannot be undone only when they said so for that kind.
CREATE TABLE action_auto_approvals (
 account_id TEXT NOT NULL, connection_id TEXT NOT NULL, kind TEXT NOT NULL,
 include_irreversible INTEGER NOT NULL DEFAULT 0 CHECK(include_irreversible IN (0,1)), set_by TEXT NOT NULL, set_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,connection_id,kind)
);
-- A handoff: work that waits for a person (an approval, a question), with what it will resume. It holds no running slot and no cell while it waits.
CREATE TABLE handoffs (
 account_id TEXT NOT NULL REFERENCES accounts(id), id TEXT NOT NULL, request_id TEXT, conversation_id TEXT, actor_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('action_approval','workflow_approval','question')),
 action_id TEXT, workflow_id TEXT,
 question TEXT NOT NULL DEFAULT '' CHECK(length(question)<=1000), options_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(options_json)),
 evidence_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(evidence_json)), resume_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(resume_json)),
 state TEXT NOT NULL CHECK(state IN ('waiting','answered','resumed','expired','cancelled')),
 answer_json TEXT CHECK(answer_json IS NULL OR json_valid(answer_json)),
 created_epoch INTEGER NOT NULL, expires_epoch INTEGER NOT NULL, answered_epoch INTEGER, resumed_request_id TEXT,
 PRIMARY KEY(account_id,id)
);
CREATE INDEX handoffs_by_state ON handoffs(state,expires_epoch);
CREATE INDEX handoffs_by_request ON handoffs(account_id,request_id);
-- A workflow: several actions, from one or more connectors, approved together and run in order; a failure walks the finished steps back.
CREATE TABLE workflows (
 account_id TEXT NOT NULL REFERENCES accounts(id), id TEXT NOT NULL, request_id TEXT, conversation_id TEXT, actor_id TEXT NOT NULL,
 title TEXT NOT NULL CHECK(length(title) BETWEEN 1 AND 200), steps_hash TEXT NOT NULL CHECK(length(steps_hash)=64),
 state TEXT NOT NULL CHECK(state IN ('proposed','approved','running','done','reversed','partly_reversed','expired','declined')),
 approved_by TEXT, approved_epoch INTEGER, report_json TEXT CHECK(report_json IS NULL OR json_valid(report_json)),
 created_epoch INTEGER NOT NULL, updated_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,id)
);
CREATE INDEX workflows_by_state ON workflows(state,updated_epoch);
-- The synthetic connector's own "provider": a fake outside system used to prove every part of the pipeline, behind a test-only switch. It holds no customer data.
CREATE TABLE synthetic_records (
 account_id TEXT NOT NULL, id TEXT NOT NULL, kind TEXT NOT NULL, folder TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '',
 version INTEGER NOT NULL DEFAULT 1, deleted INTEGER NOT NULL DEFAULT 0, idempotency_key TEXT, updated_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,id)
);
CREATE TABLE synthetic_faults (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL, operation TEXT NOT NULL, fault TEXT NOT NULL, remaining INTEGER NOT NULL DEFAULT 1
);
