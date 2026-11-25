-- A connected-app call that waits, inside the assistant's tool call, for the customer's permission (reliability plan, Part 6; owner switch `approve_in_place`).
-- `wait_until`: the moment the call stops waiting in place; `wait_seen`: the last time the waiting call said it is still there. While both hold, the run is parked and
-- the customer's decision goes back to that call; otherwise the decision reaches the assistant as before (steered into the run, or a turn of its own). Epoch seconds.
ALTER TABLE mcp_calls ADD COLUMN wait_until INTEGER;
ALTER TABLE mcp_calls ADD COLUMN wait_seen INTEGER;
