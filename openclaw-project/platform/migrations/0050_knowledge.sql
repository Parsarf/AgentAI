-- Customer knowledge (roadmap Phase 4) and the rest of the read-only mail and calendar dashboard (Phase 5: drafts). Additive: an older release ignores all of it.

-- One row per source the customer's knowledge index holds: a file they uploaded, a file their assistant made, an attachment of a message they opened. The passages,
-- their vectors and the parsed structure live in the knowledge index (its own PostgreSQL database, agentai_platform/knowledge_index.py), which is DERIVED from these rows
-- and the files themselves: removing a row's source removes them there. `ref` names the thing in its own table (an upload id, `<artifact id>:<version>`, or
-- `<connection>:<message>:<attachment>`). `origin` is what kind of source it is for citations (#46): the customer's own, an official one, or a third party's.
CREATE TABLE knowledge_sources (
 account_id TEXT NOT NULL, id TEXT NOT NULL, organization_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('upload','made','attachment')), ref TEXT NOT NULL CHECK(length(ref) BETWEEN 1 AND 700),
 name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 255), media_type TEXT NOT NULL DEFAULT 'application/octet-stream', size_bytes INTEGER NOT NULL DEFAULT 0,
 sha256 TEXT,
 project_id TEXT, pinned INTEGER NOT NULL DEFAULT 0 CHECK(pinned IN (0,1)),
 scope TEXT NOT NULL DEFAULT 'account' CHECK(scope IN ('account','organization')),
 audience TEXT NOT NULL DEFAULT '' CHECK(length(audience)<=80),            -- for scope 'organization': 'all', 'role:<role>' or 'group:<id>'
 origin TEXT NOT NULL DEFAULT 'own' CHECK(origin IN ('own','official','third_party')), source_epoch INTEGER,
 state TEXT NOT NULL CHECK(state IN ('queued','working','ready','failed','removing')), step TEXT, error TEXT CHECK(error IS NULL OR length(error)<=200),
 parser TEXT, pages INTEGER, passages INTEGER NOT NULL DEFAULT 0, tables INTEGER NOT NULL DEFAULT 0, charts INTEGER NOT NULL DEFAULT 0,
 model_pages INTEGER NOT NULL DEFAULT 0, cost_microusd INTEGER NOT NULL DEFAULT 0, low_confidence INTEGER NOT NULL DEFAULT 0, unread_pages INTEGER NOT NULL DEFAULT 0,
 version_token TEXT, added_by TEXT NOT NULL, added_epoch INTEGER NOT NULL, updated_epoch INTEGER NOT NULL, indexed_epoch INTEGER,
 attempts INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_until INTEGER, not_before INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(account_id,id)
);
CREATE UNIQUE INDEX knowledge_sources_ref ON knowledge_sources(account_id,kind,ref);
CREATE INDEX knowledge_sources_work ON knowledge_sources(state,not_before);
CREATE INDEX knowledge_sources_shared ON knowledge_sources(organization_id,scope,state);

-- What the assistant checked during a task, for the task's result (#47, #48): a claim checked against its passage, a search that was partial, a page that could not be read.
-- Fixed words and ids only: the claim's text is never stored here.
CREATE TABLE knowledge_checks (
 account_id TEXT NOT NULL, request_id TEXT NOT NULL, id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('claim','search','read','federated')), outcome TEXT NOT NULL CHECK(length(outcome) BETWEEN 1 AND 40),
 detail_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(detail_json)), created_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,request_id,id)
);

-- Named groups of an organization's people (#40): shared knowledge can be meant for one group only.
CREATE TABLE organization_groups (
 organization_id TEXT NOT NULL REFERENCES organizations(id), id TEXT NOT NULL, name TEXT NOT NULL CHECK(length(name) BETWEEN 1 AND 80), created_epoch INTEGER NOT NULL,
 PRIMARY KEY(organization_id,id)
);
CREATE UNIQUE INDEX organization_groups_name ON organization_groups(organization_id,lower(name));
CREATE TABLE organization_group_members (
 organization_id TEXT NOT NULL, group_id TEXT NOT NULL, actor_id TEXT NOT NULL, created_epoch INTEGER NOT NULL,
 PRIMARY KEY(organization_id,group_id,actor_id),
 FOREIGN KEY(organization_id,group_id) REFERENCES organization_groups(organization_id,id)
);

-- Decisions and commitments (#43): what, who owns it, when it is due, where it came from, and its state. One found in outside content (an email, a document) starts as
-- 'proposed' and counts only once the customer confirms it. `history_json` is every change, oldest first.
CREATE TABLE commitments (
 account_id TEXT NOT NULL, id TEXT NOT NULL,
 kind TEXT NOT NULL DEFAULT 'commitment' CHECK(kind IN ('commitment','decision')),
 what TEXT NOT NULL CHECK(length(what) BETWEEN 1 AND 500), owner TEXT NOT NULL DEFAULT '' CHECK(length(owner)<=200),
 due_epoch INTEGER, due_zone TEXT, due_has_time INTEGER NOT NULL DEFAULT 0 CHECK(due_has_time IN (0,1)),
 source_kind TEXT NOT NULL CHECK(source_kind IN ('conversation','email','document','meeting','customer')), source_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(source_json)),
 origin TEXT NOT NULL CHECK(origin IN ('customer','outside')),
 state TEXT NOT NULL CHECK(state IN ('proposed','open','done','dropped')),
 request_id TEXT, created_epoch INTEGER NOT NULL, updated_epoch INTEGER NOT NULL,
 history_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(history_json)),
 PRIMARY KEY(account_id,id)
);
CREATE INDEX commitments_state ON commitments(account_id,state,due_epoch);

-- Mail drafts (#57). A Lumina record only: nothing is created in the mailbox in this phase. `connection_id` is the account it would be sent from.
CREATE TABLE hub_drafts (
 account_id TEXT NOT NULL, id TEXT NOT NULL, connection_id TEXT NOT NULL, thread_id TEXT,
 to_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(to_json)), cc_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(cc_json)),
 subject TEXT NOT NULL DEFAULT '' CHECK(length(subject)<=500), body TEXT NOT NULL DEFAULT '' CHECK(length(body)<=40000),
 origin TEXT NOT NULL CHECK(origin IN ('customer','assistant')), request_id TEXT,
 state TEXT NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','discarded')),
 created_epoch INTEGER NOT NULL, updated_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,id),
 FOREIGN KEY(account_id,connection_id) REFERENCES connector_connections(account_id,id)
);
CREATE INDEX hub_drafts_thread ON hub_drafts(account_id,connection_id,thread_id);

-- Memory correction (#42): an entry corrected by the customer keeps its id; what it said before is kept here, with where it came from and when.
CREATE TABLE longterm_memory_history (
 account_id TEXT NOT NULL, entry_id TEXT NOT NULL, version INTEGER NOT NULL,
 content TEXT NOT NULL, source TEXT NOT NULL CHECK(source IN ('customer','agent')), written_epoch INTEGER NOT NULL,
 replaced_epoch INTEGER NOT NULL, replaced_by TEXT NOT NULL CHECK(replaced_by IN ('customer','agent')),
 PRIMARY KEY(account_id,entry_id,version)
);
