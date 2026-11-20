-- A sign-in that adds permissions to a connection the customer already has (roadmap Phase 6: sending, organizing, changing events, each asked for on first use). The
-- state remembers which connection it upgrades: finishing it replaces that connection's tokens and permissions in place and keeps its grants and its synced copy (a new
-- connection to the same account would revoke the old one and delete its copy). Additive: an older release ignores the column.
ALTER TABLE connector_link_states ADD COLUMN upgrade_connection_id TEXT CHECK(upgrade_connection_id IS NULL OR length(upgrade_connection_id) BETWEEN 1 AND 64);
-- Availability (roadmap Phase 6, #59): the customer's working hours per weekday, notice, buffer between meetings, which calendars count as busy, whether tentative and
-- all-day events count. Their own settings; the defaults are applied when this is empty.
ALTER TABLE hub_settings ADD COLUMN availability_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(availability_json));
-- A change the customer made with their own hand in the Inbox or the Calendar (pressing Send, Archive, dragging an event): their press is the approval, and the screen
-- it came from is recorded here. NULL for every change the assistant prepared, whatever screen it was approved on (an approval of a prepared change is never "direct").
ALTER TABLE actions ADD COLUMN direct_screen TEXT CHECK(direct_screen IS NULL OR direct_screen IN ('inbox','calendar','settings'));
