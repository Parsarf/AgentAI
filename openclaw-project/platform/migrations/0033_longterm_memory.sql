-- Long-term memory ledger (agentai_platform/longterm_memory.py). One row per thing the assistant was asked to remember for a customer.
-- The ledger is Lumina's source of truth: what the customer can see and delete. The Hindsight server only indexes it (document id = id here, bank = a keyed hash of the account).
-- status: pending (written here, not yet indexed), active, deleting (content already blanked, index removal still to be confirmed), deleted.
CREATE TABLE longterm_memories (
 account_id TEXT NOT NULL REFERENCES accounts(id), id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('preference','fact')),
 source TEXT NOT NULL CHECK(source IN ('customer','agent')),
 content TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','active','deleting','deleted')),
 created_epoch INTEGER NOT NULL, updated_epoch INTEGER NOT NULL,
 PRIMARY KEY(account_id,id)
);
CREATE INDEX longterm_memories_status ON longterm_memories(account_id,status,created_epoch);
