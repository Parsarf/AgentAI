-- Where a customer message was typed when it was not the web chat: the side panel in their own Chrome. NULL = the web chat (or Telegram), as before.
ALTER TABLE chat_messages ADD COLUMN surface TEXT CHECK(surface IS NULL OR surface IN ('panel'));
