# Objective checkpoint

This is a Markdown artifact convention, not a native goal/task schema.

- Native goal ID: <returned ID>
- Owner session key: <exact originating session>
- Objective and scope: <owner-approved outcome and writable roots>
- Source revision: <actual revision and initial dirty state>
- Plan and steps: <pending/running/waiting/complete with observed artifacts>
- Native task/flow/run IDs: <returned IDs only; none if no detached work>
- Receipts: <stable operation ID, exact payload, native/provider receipt>
- Last confirmed progress: <dated observation>
- Errors and blocker: <observed cause; do not expose hidden reasoning>
- Verification: <pending/deferred, or actual commands/results>
- Billing: <existing route/caps; unknown cost remains unknown>
- Stop condition: <complete criteria or owner cancellation>
- Resume: <read current native state, reconcile receipts, continue explicitly>

Cancellation: pause/clear the goal as appropriate, cancel owned child tasks or
flows, disable/remove only the related automation, and retain outcome evidence.
