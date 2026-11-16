-- The mail and calendar dashboard (roadmap #D1 provider-neutral model, #D2 connected accounts and sync). Additive: an older release ignores all of it.
-- Every provider is converted to these shapes at its adapter; nothing below is specific to one provider. The uniqueness of (account, connection, provider id) is what makes
-- a sync that runs twice change nothing.

-- One row per thing that is synced: a connection's mail ('mail', '*') or one of its calendars ('calendar', <calendar id>). The cursor is the provider's own "what changed
-- since" token, opaque here. A lease keeps two workers off one row.
CREATE TABLE hub_sync (
 account_id TEXT NOT NULL, connection_id TEXT NOT NULL,
 domain TEXT NOT NULL CHECK(domain IN ('mail','calendar')), resource_id TEXT NOT NULL CHECK(length(resource_id) BETWEEN 1 AND 300),
 cursor TEXT CHECK(cursor IS NULL OR length(cursor)<=4000),
 grant_key TEXT NOT NULL DEFAULT '',                                 -- what was granted when this row was last filled: a change of grants refills it
 filled INTEGER NOT NULL DEFAULT 0 CHECK(filled IN (0,1)),          -- the first fill of the window has finished
 window_start_epoch INTEGER, window_end_epoch INTEGER,
 state TEXT NOT NULL DEFAULT 'waiting' CHECK(state IN ('waiting','running','paused')),
 last_sync_epoch INTEGER, last_change_epoch INTEGER, next_epoch INTEGER NOT NULL DEFAULT 0, lease_epoch INTEGER,
 failures INTEGER NOT NULL DEFAULT 0, last_error TEXT CHECK(last_error IS NULL OR length(last_error)<=40), last_error_epoch INTEGER,
 item_count INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(account_id,connection_id,domain,resource_id),
 FOREIGN KEY(account_id,connection_id) REFERENCES connector_connections(account_id,id)
);
CREATE INDEX hub_sync_due ON hub_sync(next_epoch) WHERE state='waiting';

-- Mail. Headers and a short snippet for the synced window; the body only once the message has been opened or read by the assistant (body_fetched_epoch), and then only
-- until its retention ends. Labels are the common set (inbox, sent, drafts, archive, spam, trash, starred, unread); the provider's own names are kept beside them.
CREATE TABLE hub_messages (
 account_id TEXT NOT NULL, connection_id TEXT NOT NULL, id TEXT NOT NULL CHECK(length(id) BETWEEN 1 AND 300), thread_id TEXT NOT NULL CHECK(length(thread_id) BETWEEN 1 AND 300),
 subject TEXT NOT NULL DEFAULT '' CHECK(length(subject)<=500), snippet TEXT NOT NULL DEFAULT '' CHECK(length(snippet)<=400),
 sender_json TEXT NOT NULL CHECK(json_valid(sender_json)), to_json TEXT NOT NULL CHECK(json_valid(to_json)), cc_json TEXT NOT NULL CHECK(json_valid(cc_json)),
 people_text TEXT NOT NULL DEFAULT '',                               -- names and addresses in one lower-case line, for search
 sent_epoch INTEGER NOT NULL,
 labels_json TEXT NOT NULL CHECK(json_valid(labels_json)), provider_labels_json TEXT NOT NULL CHECK(json_valid(provider_labels_json)),
 unread INTEGER NOT NULL DEFAULT 0 CHECK(unread IN (0,1)), starred INTEGER NOT NULL DEFAULT 0 CHECK(starred IN (0,1)),
 has_attachments INTEGER NOT NULL DEFAULT 0 CHECK(has_attachments IN (0,1)),
 body_text TEXT, body_html TEXT, attachments_json TEXT CHECK(attachments_json IS NULL OR json_valid(attachments_json)),
 body_fetched_epoch INTEGER, body_opened_epoch INTEGER,
 synced_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,connection_id,id),
 FOREIGN KEY(account_id,connection_id) REFERENCES connector_connections(account_id,id)
);
CREATE INDEX hub_messages_by_thread ON hub_messages(account_id,connection_id,thread_id,sent_epoch);
CREATE INDEX hub_messages_bodies ON hub_messages(body_opened_epoch) WHERE body_fetched_epoch IS NOT NULL;

-- A thread is the list row: derived from its messages by the sync engine, never written by an adapter.
CREATE TABLE hub_threads (
 account_id TEXT NOT NULL, connection_id TEXT NOT NULL, id TEXT NOT NULL CHECK(length(id) BETWEEN 1 AND 300),
 subject TEXT NOT NULL DEFAULT '', snippet TEXT NOT NULL DEFAULT '', people_json TEXT NOT NULL CHECK(json_valid(people_json)), people_text TEXT NOT NULL DEFAULT '',
 last_epoch INTEGER NOT NULL, message_count INTEGER NOT NULL,
 unread INTEGER NOT NULL DEFAULT 0 CHECK(unread IN (0,1)), starred INTEGER NOT NULL DEFAULT 0 CHECK(starred IN (0,1)),
 has_attachments INTEGER NOT NULL DEFAULT 0 CHECK(has_attachments IN (0,1)),
 labels_json TEXT NOT NULL CHECK(json_valid(labels_json)), provider_labels_json TEXT NOT NULL CHECK(json_valid(provider_labels_json)),
 PRIMARY KEY(account_id,connection_id,id),
 FOREIGN KEY(account_id,connection_id) REFERENCES connector_connections(account_id,id)
);
CREATE INDEX hub_threads_list ON hub_threads(account_id,last_epoch DESC,connection_id,id);

-- Calendars of a connection. `selected` and `colour` are the customer's own choices in the dashboard; `access` is what the provider says this connection may do there.
CREATE TABLE hub_calendars (
 account_id TEXT NOT NULL, connection_id TEXT NOT NULL, id TEXT NOT NULL CHECK(length(id) BETWEEN 1 AND 300),
 name TEXT NOT NULL DEFAULT '' CHECK(length(name)<=200), provider_colour TEXT CHECK(provider_colour IS NULL OR length(provider_colour)<=20),
 colour TEXT CHECK(colour IS NULL OR length(colour)<=20), timezone TEXT CHECK(timezone IS NULL OR length(timezone)<=64),
 access TEXT NOT NULL DEFAULT 'read' CHECK(access IN ('busy','read','write','owner')), is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0,1)),
 selected INTEGER NOT NULL DEFAULT 1 CHECK(selected IN (0,1)), updated_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,connection_id,id),
 FOREIGN KEY(account_id,connection_id) REFERENCES connector_connections(account_id,id)
);

-- Events, as the provider's own expanded instances (recurrence rules are never expanded here). An instance keeps its series, whether it is an exception and whether it
-- is cancelled. All-day events keep their dates as the provider gave them (a date has no timezone); timed events are epoch seconds plus the event's own timezone.
CREATE TABLE hub_events (
 account_id TEXT NOT NULL, connection_id TEXT NOT NULL, calendar_id TEXT NOT NULL, id TEXT NOT NULL CHECK(length(id) BETWEEN 1 AND 400),
 series_id TEXT CHECK(series_id IS NULL OR length(series_id)<=400),
 title TEXT NOT NULL DEFAULT '' CHECK(length(title)<=500),
 start_epoch INTEGER NOT NULL, end_epoch INTEGER NOT NULL, all_day INTEGER NOT NULL DEFAULT 0 CHECK(all_day IN (0,1)),
 start_date TEXT CHECK(start_date IS NULL OR length(start_date)=10), end_date TEXT CHECK(end_date IS NULL OR length(end_date)=10),
 timezone TEXT CHECK(timezone IS NULL OR length(timezone)<=64),
 place TEXT NOT NULL DEFAULT '' CHECK(length(place)<=500), conference_url TEXT CHECK(conference_url IS NULL OR length(conference_url)<=1000),
 organizer_json TEXT CHECK(organizer_json IS NULL OR json_valid(organizer_json)), attendees_json TEXT NOT NULL CHECK(json_valid(attendees_json)),
 people_text TEXT NOT NULL DEFAULT '',
 my_response TEXT CHECK(my_response IS NULL OR my_response IN ('accepted','declined','tentative','needs_action')),
 is_exception INTEGER NOT NULL DEFAULT 0 CHECK(is_exception IN (0,1)), cancelled INTEGER NOT NULL DEFAULT 0 CHECK(cancelled IN (0,1)),
 visibility TEXT NOT NULL DEFAULT 'default' CHECK(visibility IN ('default','public','private','busy')),
 version TEXT CHECK(version IS NULL OR length(version)<=200), description TEXT NOT NULL DEFAULT '' CHECK(length(description)<=8000),
 provider_url TEXT CHECK(provider_url IS NULL OR length(provider_url)<=1000),
 updated_epoch INTEGER, synced_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,connection_id,calendar_id,id),
 FOREIGN KEY(account_id,connection_id) REFERENCES connector_connections(account_id,id)
);
CREATE INDEX hub_events_range ON hub_events(account_id,start_epoch,end_epoch);

-- The customer's own settings for the dashboard: the timezone everything is shown in (NULL: the browser's), and whether opening a sender's or a message's remote
-- pictures was allowed.
CREATE TABLE hub_settings (
 account_id TEXT NOT NULL PRIMARY KEY REFERENCES accounts(id),
 timezone TEXT CHECK(timezone IS NULL OR length(timezone)<=64),
 image_senders_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(image_senders_json)),
 updated_epoch INTEGER NOT NULL
);
