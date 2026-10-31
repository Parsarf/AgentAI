-- Choices the customer asked Lumina to remember for next time (size M, usual drink). Plain words only: logins and cards are never stored here.
CREATE TABLE saved_choices (
  account_id TEXT NOT NULL,
  field TEXT NOT NULL,
  value TEXT NOT NULL,
  created_epoch INTEGER NOT NULL,
  updated_epoch INTEGER NOT NULL,
  PRIMARY KEY(account_id,field)
);
