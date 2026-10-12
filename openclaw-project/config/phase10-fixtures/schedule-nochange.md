# No-change schedule fixture (synthetic)

Schedule: daily 09:00 in Europe/Berlin with a watcher on a fixed local file.
- Tick 1: baseline recorded, no model call.
- Tick 2 (same day boundary next day, file unchanged): zero model calls,
  no notification, day consumed.
- Change the file: next tick requests admission once; denial leaves state
  unadvanced and retries; grant yields exactly one notification.
- Unattended approval expired: deny, no run.
- Verify the installed scheduler's capacity (historical value eight) and that
  pre-existing jobs keep firing. No exactly-once claim.
