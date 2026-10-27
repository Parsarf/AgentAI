-- Saved logins and cards the customer chose to keep, encrypted (AES-256-GCM, a key per account, the key file kept outside this database).
-- Only the label, kind, site and a short hint are readable here; the card security code is never stored.
CREATE TABLE vault_items (
  account_id TEXT NOT NULL,
  id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('login','card')),
  label TEXT NOT NULL,
  site TEXT NOT NULL DEFAULT '',
  hint TEXT NOT NULL DEFAULT '',
  kid TEXT NOT NULL,
  nonce BLOB NOT NULL,
  ciphertext BLOB NOT NULL,
  accepted_epoch INTEGER NOT NULL,
  created_epoch INTEGER NOT NULL,
  last_used_epoch INTEGER,
  PRIMARY KEY(account_id,id)
);
