-- Archived conversations disappear from lists and no longer count toward the per-project limit; nothing is deleted.
ALTER TABLE conversations ADD COLUMN archived_epoch INTEGER;
