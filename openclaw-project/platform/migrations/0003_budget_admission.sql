CREATE TABLE task_reservations (
 account_id TEXT NOT NULL, task_id TEXT NOT NULL, idempotency_key TEXT NOT NULL,
 request_hash TEXT NOT NULL, entitlement_id TEXT NOT NULL, amount_microusd INTEGER NOT NULL CHECK(amount_microusd>0),
 state TEXT NOT NULL CHECK(state IN ('active','uncertain','settled','cancelled')),
 created_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,task_id), UNIQUE(account_id,idempotency_key),
 FOREIGN KEY(account_id,task_id) REFERENCES tasks(account_id,id),
 FOREIGN KEY(account_id,entitlement_id) REFERENCES entitlements(account_id,id)
);
CREATE TABLE provider_receipts (
 account_id TEXT NOT NULL, task_id TEXT NOT NULL, provider TEXT NOT NULL, provider_request_id TEXT NOT NULL,
 payload_hash TEXT NOT NULL, price_version TEXT NOT NULL, amount_microusd INTEGER NOT NULL CHECK(amount_microusd>=0),
 observed_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,provider,provider_request_id),
 FOREIGN KEY(account_id,task_id) REFERENCES tasks(account_id,id)
);
CREATE TRIGGER receipt_no_update BEFORE UPDATE ON provider_receipts BEGIN SELECT RAISE(ABORT,'receipt is append only'); END;
CREATE TRIGGER receipt_no_delete BEFORE DELETE ON provider_receipts BEGIN SELECT RAISE(ABORT,'receipt is append only'); END;
