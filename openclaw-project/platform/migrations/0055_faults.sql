-- Why something did not finish (reliability plan, Part 1). One row per failure or expected stop, written where it is caught: a kind from a closed list, a registered
-- reason code, who must act, and what was changed. `detail_json` holds facts only (a status number, an exception type, a state name): never page text, message text, an
-- address or a name (faults.py enforces the shape). `expected` is 1 for a stop that is not an error (a limit the customer set, a wait for the customer), so an error
-- rate counts only the rows where it is 0. Kept 30 days (retention.py, rule `diagnostics`).
CREATE TABLE faults (
 account_id TEXT NOT NULL, id TEXT NOT NULL, request_id TEXT, feature TEXT NOT NULL CHECK(length(feature) BETWEEN 1 AND 40),
 kind TEXT NOT NULL CHECK(kind IN ('retry_later','needs_customer','needs_owner','refused','not_found','conflict','invalid','limit','unknown_outcome','internal')),
 reason TEXT NOT NULL CHECK(length(reason) BETWEEN 3 AND 80),
 actor TEXT NOT NULL CHECK(actor IN ('assistant','customer','owner','nobody')),
 effect TEXT NOT NULL CHECK(effect IN ('nothing_changed','partly_done','unknown')),
 expected INTEGER NOT NULL DEFAULT 0 CHECK(expected IN (0,1)), retry_after_epoch INTEGER,
 detail_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(detail_json) AND length(detail_json)<=1000), created_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,id)
);
CREATE INDEX faults_request ON faults(account_id,request_id);
CREATE INDEX faults_time ON faults(created_epoch);

-- One row per model call that passed through Lumina's model relay: how it ended and how long it took. No prompt, no reply, no model name the customer typed: the route
-- ('lumina' or 'own'), the final HTTP status, the relay's own code when it refused, times in milliseconds, and the token counts the provider reported (when it did).
-- `request_id` is set when exactly one task of the account was running (a model call cannot say which task it is for). Kept 30 days.
CREATE TABLE model_calls (
 account_id TEXT NOT NULL, id TEXT NOT NULL, request_id TEXT, route TEXT NOT NULL CHECK(route IN ('lumina','own')),
 status INTEGER NOT NULL CHECK(status BETWEEN 0 AND 599), code TEXT NOT NULL DEFAULT '' CHECK(length(code)<=60),
 waited_ms INTEGER NOT NULL DEFAULT 0, answer_ms INTEGER NOT NULL DEFAULT 0, total_ms INTEGER NOT NULL DEFAULT 0, reply_bytes INTEGER NOT NULL DEFAULT 0,
 input_tokens INTEGER, output_tokens INTEGER, cached_tokens INTEGER, created_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,id)
);
CREATE INDEX model_calls_request ON model_calls(account_id,request_id);
CREATE INDEX model_calls_time ON model_calls(created_epoch);

-- A request made by the deploy's own acceptance run, not by a person: counted apart, so probes neither hide nor inflate what customers experienced.
ALTER TABLE customer_requests ADD COLUMN probe INTEGER NOT NULL DEFAULT 0 CHECK(probe IN (0,1));
-- The acceptance run's requests so far, by the one sentence it has always sent.
UPDATE customer_requests SET probe=1 WHERE message='Reply with exactly the word: ok';
