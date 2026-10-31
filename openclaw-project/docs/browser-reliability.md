# Browser reliability fixes — 27 October 2026

Update 28 October: the original transcript-based ownership check subsequently rejected valid YoungLA and restaurant calls. Protocol 2 replaces that check with runtime-issued, one-use tool proofs; see [browser-tool-ownership.md](browser-tool-ownership.md). The historical table below describes the first hardening pass.

These changes address the production traces examined on 27 October. They are source changes pending coordinated deployment; they do not certify merchant checkout success or change spending limits.

| Observed failure | Change |
| --- | --- |
| Full On product URLs became the homepage | Preserve the case-sensitive path, query and fragment; pass `start_url` explicitly so URLs in task prose cannot choose the starting page. Reject credentials, explicit ports, unsafe schemes and malformed sites. The browser's public-network and navigation policy still applies. |
| Neem → Brook → Neem and repeated White selections looked like progress | Hand the page back to Claude after a semantic option cycle or three identical selections, even when pixels or URLs change. No new confidence threshold. |
| Product controls fell outside the first 20 DOM controls | Visible uncovered controls replace offscreen/covered controls, preserving the final page order and old-runner behavior. |
| Broad comparison/search/cart/checkout prompts | Tool descriptions and provisioned workspace rules require bounded stages: inspect and report options, let Claude rank the observations, then act on the selected option. This is a prompting contract, not a guarantee that every model obeys it. |
| Repeated startup failures | After two consecutive browser attempts fail, refuse another startup attempt for that request (a successful inspection resets the streak) and explain the fallback. The separate host runner remains the default. |
| An old YoungLA session attached work to a new UI request | The root bridge resolves the native runtime's live turn claim and latest pending tool call. The MCP relay matches its session and run to an admitted funded delivery. Missing, stale, completed, mismatched or ambiguous origins fail closed. Both browser tools and task-progress updates use the verified request; a bound call cannot fall back to the newest account task. |
| Other native conversations could run alongside the new usage baseline | Read a bounded inventory of active native turns before new work. Abort unowned turns, wait for owned turns, and drain them before taking the provider spend baseline. Historical conversations are not individually scanned. |
| JEV metrics were always zero | Count actual admitted JEV requests, including failed responses, and mirror `jev_calls`/`jev_acted`. Legacy storage names `jev_asked`/`jev_agree` now carry these counters for the most recent browser session; older producers retain their legacy fallback. An action/request ratio is not a task success rate. |

## Trust boundary and runtime compatibility

The cell credential identifies the account only. Neither a model-written task ID nor MCP request metadata proves the originating run. The root bridge reads the pinned OpenClaw 2026.9.6 runtime's SQLite placement claims and transcript records, including compressed events. It verifies the transcript's native `__openclaw.runId`, exact tool arguments and lack of a matching tool result, then returns only session/run/call identity. No transcript content is returned or logged by this reader. The relay requires a matching conversation, native delivery and active reservation. Cancellation continues to stop the original browser job.

Unsupported runtime schemas or unavailable state refuse tool calls. A runtime upgrade must repeat this compatibility acceptance. The account-wide provider key remains the source of billed spend: historical per-task receipts cannot be retrospectively corrected from these guards, and draining current turns does not provide provider-level per-run billing isolation.

## Validation and rollout

Regression coverage includes exact product URLs, wrong bound request IDs, option cycles, visible controls, startup retry limits, current counters, compressed/corrupt transcripts, run mismatch, completed calls and ambiguous origins. A real OpenClaw gateway with a synthetic model verifies both a legitimate browser call and rejection of an old conversation's resumed browser call while a new task is admitted. These checks do not spend provider allowance.

Evidence is stored in `../evidence/browser-reliability/20261027/`. Production merchant/model acceptance remains separate. The earlier UI pilot's browser activity came from an old shopping session; it is not evidence that the UI task browsed successfully.

Deploy matching platform and supervisor code together: the root cell bridge runs from `/opt/agentai-supervisor/current`, while the worker and MCP relay run from `/opt/agentai-platform/current`. Roll out the bridge's new `tools.origin`/`tools.active` methods before enabling the new worker/relay; drain work and restart those services together. Refresh existing cells' provisioned workspace rules with the existing `CellProvisioner.write_rules` path before their next session; new cells get the rules automatically. Preserve the previous release pair for rollback. No database migration is needed. The HTTP canary alone does not exercise the separate root bridge or MCP service.
