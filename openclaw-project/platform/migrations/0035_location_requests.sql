-- One consent attempt per admitted task. Position is cleared on consumption/expiry.
CREATE TABLE location_requests (
 account_id TEXT NOT NULL REFERENCES accounts(id),
 request_id TEXT NOT NULL,
 id TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','granted','denied','unavailable','timeout','cancelled')),
 expires_epoch INTEGER NOT NULL,
 client_id TEXT,
 claim_until INTEGER NOT NULL DEFAULT 0,
 position_json TEXT,
 PRIMARY KEY(account_id,request_id),
 UNIQUE(account_id,id),
 FOREIGN KEY(account_id,request_id) REFERENCES customer_requests(account_id,id)
);
CREATE INDEX location_pending ON location_requests(account_id,status,expires_epoch);
