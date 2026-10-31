# Lumina: current architecture and execution reports

Rebuilt 29 October 2026 after the owner approved replacing superseded reports
and diagrams. Start with the four reports below. They describe the current
checked-in native-execution system and explicitly separate source evidence,
recorded production verification, unfinished features and open defects.

| Report | Main questions |
|---|---|
| [System overview](system-overview.md) | What runs, how the edge/cells/owner plane connect, and how a release rolls back. |
| [Native execution](native-execution.md) | Send/steer, admission, queue/worker/driver, protocol-2 ownership, browser decisions and controls. |
| [State and recovery](state-and-recovery.md) | Requests versus tasks/deliveries/browser jobs, persistent data, leases, parking and recovery. |
| [Current findings](findings.md) | Which defects remain open, which old claims were corrected, and what has not been verified. |

The four reports replace the old `docs/orchestration-audit/` report set and
its rendered diagrams, the previous pre-native `findings.md` content and the
September readiness review. Recovery archives and Git history are retained;
no orphaned product implementation was deleted as part of this documentation
cleanup. The [cleanup record](../../../docs/codebase-audit/CLEANUP_REVIEW.md)
contains the exact approved scope.

## Rendered current diagrams

| Report | SVG exports |
|---|---|
| System overview | [Components and trust boundaries](svg/system-overview-1.svg), [release process](svg/system-overview-2.svg) |
| Native execution | [Send/steer/run](svg/native-execution-1.svg), [tool proof](svg/native-execution-2.svg), [browser control](svg/native-execution-3.svg) |
| State and recovery | [Persistence ownership](svg/state-and-recovery-1.svg), [request transitions](svg/state-and-recovery-2.svg) |

Mermaid blocks in the reports are the source of truth for these SVG exports.
A [render manifest](svg/current-diagrams.json) records input and output hashes; regenerate the export when
a block changes. These diagrams describe code, not a new runtime test result.

## Other documents retained

- [Native browser plan](native-browser-plan.md): an active rollout plan, not proof of production cutover.
- `agent-execution.md`, `tool-routing.md`, `task-lifecycle.md`: explicitly historical pages. The owner selected **no changes** to Batch D; their text and old SVGs remain untouched. Their links to findings.md now reach the replacement report.
- [Detailed ownership protocol](../browser-tool-ownership.md), [historical reliability fixes](../browser-reliability.md).
- [Codebase audit index](../../../docs/codebase-audit/README.md), [implementation status](../../../docs/codebase-audit/IMPLEMENTATION_PROGRESS.md), [deployment verification](../../../docs/codebase-audit/DEPLOYMENT_2026-10-29.md).
- [Task-progress verification](../../evidence/task-progress/README.md): restored prior evidence, not newly captured screenshots.

Do not run old executable prompts to infer current status. Consult current
source and the progress/deployment records. No real server command, customer
request or paid evaluation was run to rebuild these reports.
