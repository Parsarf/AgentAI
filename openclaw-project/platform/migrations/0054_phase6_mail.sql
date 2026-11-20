-- Mail from the dashboard (roadmap Phase 6, #66, #67, #D6). The customer's own mail settings: how long "Undo send" waits (default 10 seconds), whether opening a message
-- marks it read at the provider (default no), and their own limits on sending (people per message, messages per hour), which can only be lower than the platform's and
-- their organization's.
ALTER TABLE hub_settings ADD COLUMN mail_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(mail_json));
-- A draft is sent at most once (#66): the change that sent it. A sent draft is no longer listed as a draft. Additive: an older release ignores the column.
ALTER TABLE hub_drafts ADD COLUMN sent_action_id TEXT CHECK(sent_action_id IS NULL OR length(sent_action_id) BETWEEN 1 AND 64);
