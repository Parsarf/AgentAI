# Phase 4 continuation: host custody and recoverable dispatch

Outcome: implement the missing narrow supervisor boundary without giving the
web application host execution authority. Requirements: TENANT-01/02/03.
Canonical phase order and all 121 requirements are preserved.

Implement host-owned enrollment, independent durable operation journal, global
effect serialization, exact claim validation, receipt fences, and bounded Unix
socket transport authenticated by local peer identity. Binding enrollment is a
host operator action, never an application request. Use the existing native
Driver interface; no replacement agent loop, arbitrary command/path/env API,
or fallback to owner credentials. Add deployment template and recovery procedure.

The native backend remains disabled until installed Fleet compatibility, secret
custody, stronger worker runtime, disk/network quotas, drain receipts and usable
capacity have been proved. The host CLI emitted owner-config incompatibility
diagnostics, then SSH timed out. No production mutation was attempted. A native
backend cannot safely be guessed from that failed probe.

Changes: lifecycle types/coordinator, supervisor/journal/transport, dedicated
service template, focused supervisor boundary tests and phase records.
Checks: claim injection, foreign binding, stale fence, changed replay, duplicate
dispatch, independent supervisor instances, crash uncertainty, reconciliation,
global active/uncertain hold, private file modes and bounded IPC decoding.
Budget: zero paid provider calls; no new infrastructure purchase or invitation.
Rollback: revert these source changes; no production migration or service change.
Resume native provisioning on this VPS when read-only connectivity is restored.

Connectivity recovered during implementation; public login200 and healthy owner
Gateway/database were observed. The host CLI is2026.2.24/Node22, not the earlier
Fleet2026.9.6 target. Added a separate integrity-pinned CLI candidate installer,
bounded by384MiB/no swap/25% CPU/64 tasks/10min, with512MiB owner headroom.
This does not activate cells, replace owner tools or prove a task profile.
