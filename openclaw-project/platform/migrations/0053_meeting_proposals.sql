-- Meeting scheduling (roadmap Phase 6, #65): the times the assistant found for a meeting, drawn on the Calendar for the customer to pick. Who it is with (addresses the
-- customer or their assistant named), how long, the suggested times, and which people's free time could be checked (internal) and which could not (external, who are
-- offered the times by a draft email). Removed with the connection; a proposal that was picked or dismissed is removed after 30 days (retention: meeting_proposals).
CREATE TABLE meeting_proposals (
 account_id TEXT NOT NULL, id TEXT NOT NULL, connection_id TEXT NOT NULL,
 title TEXT NOT NULL DEFAULT '' CHECK(length(title)<=500), minutes INTEGER NOT NULL CHECK(minutes BETWEEN 5 AND 1440),
 attendees_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(attendees_json)), internal_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(internal_json)),
 external_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(external_json)), options_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(options_json)),
 timezone TEXT NOT NULL CHECK(length(timezone) BETWEEN 1 AND 64),
 state TEXT NOT NULL DEFAULT 'open' CHECK(state IN ('open','picked','dismissed')), handoff_id TEXT, draft_id TEXT, request_id TEXT,
 created_epoch INTEGER NOT NULL, updated_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,id),
 FOREIGN KEY(account_id,connection_id) REFERENCES connector_connections(account_id,id)
);
CREATE INDEX meeting_proposals_open ON meeting_proposals(account_id,state,updated_epoch);
