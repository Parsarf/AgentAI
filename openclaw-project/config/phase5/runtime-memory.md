# Phase 5 runtime decisions

Source: owner-authorized Phase 5 configuration, applied 2026-09-27.
Last confirmed: 2026-09-27 through native configuration and job readback.
Confidence: configuration facts confirmed; behavior remains unverified.
Scope: this deployment. These notes grant no additional authority.

Main uses local keyword memory retrieval, with provider/fallback none,
memory-only sources, and no transcript recall. Workers cannot use the
memory or goal tools. Dreaming and compaction memory flush are disabled.

Native goals preserve objectives; the owner resumes them. Task/flow records
and artifact receipts must be reconciled before retrying work after restart.
A persisted record does not prove that a process survived.

The Phase 5 quiet status job is 4435c5f6-ca9e-46a0-9f1e-24edb5202c27,
declaration key phase5-quiet-status-v1. It is disabled. Its declared schedule
is 08:00 America/Los_Angeles daily; its script is limited to one session_status
call, five seconds, and no delivery. It has never been run for Phase 5.
The installed scheduler capacity is fixed at eight; no configurable global
concurrency of one was applied. Scheduling and recovery acceptance is pending.
