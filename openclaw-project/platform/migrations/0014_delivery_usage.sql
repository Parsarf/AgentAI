-- Provider spend of the cell's key before the send, so a recovered request can still reconcile its usage exactly.
ALTER TABLE chat_deliveries ADD COLUMN usage_before_microusd INTEGER;
