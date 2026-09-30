CREATE TABLE customer_requests (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL REFERENCES accounts(id),
 id TEXT NOT NULL, actor_id TEXT NOT NULL, project_id TEXT NOT NULL,
 idempotency_key TEXT NOT NULL, payload_hash TEXT NOT NULL, message TEXT NOT NULL CHECK(length(message) BETWEEN 1 AND 16000),
 state TEXT NOT NULL CHECK(state IN ('waiting','starting','running','uncertain','completed','failed','cancelled')),
 cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
 fence INTEGER NOT NULL DEFAULT 0, lease_owner TEXT, lease_until INTEGER,
 result TEXT, created_epoch INTEGER NOT NULL,
 UNIQUE(account_id,id), UNIQUE(account_id,idempotency_key),
 FOREIGN KEY(account_id,project_id) REFERENCES projects(account_id,id)
);
CREATE TABLE request_slot (
 id INTEGER PRIMARY KEY CHECK(id=1), account_id TEXT NOT NULL, request_id TEXT NOT NULL,
 FOREIGN KEY(account_id,request_id) REFERENCES customer_requests(account_id,id)
);
