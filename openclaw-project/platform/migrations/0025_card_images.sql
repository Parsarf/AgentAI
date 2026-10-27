-- Pictures for comparison cards. The server fetches a product's picture itself (the person's browser never contacts a third-party site),
-- checks it, and keeps it here; the card only holds this image's id. Scoped to the account like every other row.
CREATE TABLE card_images (
  account_id TEXT NOT NULL REFERENCES accounts(id),
  id TEXT NOT NULL,                                   -- first 32 hex characters of the SHA-256 of the bytes
  mime TEXT NOT NULL CHECK(mime IN ('image/jpeg','image/png','image/webp')),
  width INTEGER NOT NULL,
  height INTEGER NOT NULL,
  source_host TEXT NOT NULL,                          -- the site the picture came from, shown under it
  body BLOB NOT NULL,
  created_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,id)
);
