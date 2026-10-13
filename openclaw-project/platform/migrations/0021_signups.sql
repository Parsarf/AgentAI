-- Self-service sign-ups that wait for the owner's approval. The account row stays 'suspended' until approved.
CREATE TABLE signups (
  account_id TEXT PRIMARY KEY REFERENCES accounts(id),
  state TEXT NOT NULL CHECK(state IN ('unverified','pending','approved','declined')),
  created_epoch INTEGER NOT NULL,
  verified_epoch INTEGER,
  decided_epoch INTEGER,
  decided_by TEXT,
  note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX signups_state ON signups(state,created_epoch);
