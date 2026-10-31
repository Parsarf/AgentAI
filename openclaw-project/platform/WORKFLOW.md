# Lumina end-to-end workflow

The workflow this page used to trace (assistant preamble, `lumina-step` blocks, JEV tool choice, the round loop, Pursuit, transcript polling) was replaced by native OpenClaw
execution on 26 Oct 2026. The current flow, with its sequence diagram, is in [`../docs/architecture/native-execution.md`](../docs/architecture/native-execution.md).

In one paragraph: the customer sends a message; `ChatService.send` steers it into a running task of the same chat or admits it (queue, budget reservation); the worker claims it
under the one running slot and the account's active cell; `ChatDriver` hands it to the cell's OpenClaw (`chat.send`, key = run id) and asks the runtime when the run ended
(`agent.wait`); tools, including the sandboxed browser (`lumina_browser`, MCP through `tool_relay`), run inside the runtime's own tool loop; the driver mirrors the replies, saves files
and cards, judges the outcome (`outcome.py`), settles the spend and frees the slot. Waiting for a person parks the request without the slot; Stop aborts and is confirmed by the
runtime; a goal is a chain of admitted turns.

Owner switches (`customer_execution`, `browse_tasks`, `jev_routing`, `jev_display`, `budget_caps`, ...) are re-read by the workers on every tick.
