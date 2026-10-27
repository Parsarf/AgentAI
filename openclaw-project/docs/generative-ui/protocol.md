# Response document and streaming protocol (version 1.0)

## Document

```json
{ "version": "1.0", "responseId": "resp_123",
  "datasets": { "revenue": { "columns": [{"id":"month","label":"Month"},{"id":"revenue","label":"Revenue","type":"currency"}], "rows": [ … ] } },
  "blocks": [
    {"id":"intro","type":"text","props":{"content":"Analysis complete."}},
    {"id":"metric","type":"metric_card","variant":"compact","props":{"label":"Revenue","value":24500,"format":"currency","currency":"USD"}},
    {"id":"trend","type":"line_chart","dataRef":"revenue","props":{"title":"Revenue trend","xKey":"month","series":[{"key":"revenue","label":"Revenue"}]}}
  ],
  "presentationPlan": { "advisory": true, "blocks": [ … ] } }
```

- Ordered: `blocks` order is display order. Ids are stable; the same id in a later event or line **replaces** the block in place (edit/update semantics; local state such as sort order is keyed by block id so it survives).
- Bounded: see `variants-and-properties.md`. Datasets are shared by `dataRef` (sent once, fetched once).
- Prose is ordinary message text outside the document, so Markdown and citations survive and plain readers (other clients, exports, old app versions) still get the answer.
- **Versioning:** `version` is `major.minor`. This build accepts major `1`. A document without `version` that has `blocks` is lifted to 1.0. An unknown major is refused and the prose is shown. Minor additions are new optional fields/types; the strict schemas reject fields they do not know, so a **new** field needs a minor bump and a release of both validators together (the registry JSON is regenerated from one source).
- **Old messages:** plain-text messages need no migration. They have no document row and render exactly as before.
- **Persistence and hydration:** the server stores one `document` row per reply (`data_blocks`, migration 0029) after validating; `GET /v1/conversations/{id}/blocks` returns it; the browser re-validates before drawing. Reloading the chat returns the same structured result.

## Wire format inside a reply (text-first envelope)

```
Revenue grew in five of six months.            ← prose, shown immediately
```lumina-doc
{"responseId":"resp_123"}                      ← optional header
{"dataset":"revenue","columns":[…],"rows":[…]} ← shared data
{"id":"trend","type":"line_chart","dataRef":"revenue","props":{…}}   ← one block per line
{"id":"next","type":"follow_up","props":{"suggestions":["Compare another period?"]}}
```
```

A fence may instead hold a single JSON document. A line is parsed only when complete, so incomplete JSON is never parsed. Why not a structured-output API: forcing the whole reply into a JSON schema would delay the first prose token and couple prose to widget validity. Trade-off: a widget exists only once its line completes; until then a placeholder shows.

## Streaming events (`protocol.ts`)

`response.started`, `block.started`, `block.delta`, `block.completed`, `block.updated`, `dataset.completed`, `response.completed`, `response.error`; each has `seq` and `responseId`.

| Concern | Behaviour |
|---|---|
| Prose | `block.started` (text) then `block.delta`s grow one stable text block |
| Complex widgets | placeholder (`pending`) from `block.started`; mounted only after `block.completed` validates |
| Invalid block | becomes an `invalid` slot with fallback text; the rest continue |
| Out of order | events with a gap are held (≤ 64) and applied when the gap fills |
| Duplicates / replay | `seq ≤ lastSeq` is ignored |
| Another response | ignored (events carry `responseId`) |
| Cancellation / error | `response.error {retriable}` keeps what arrived; a retry starts a new `responseId` |
| Reconnect | resume by replaying; duplicates are harmless |
| Unfinished at completion | pending widgets degrade to "did not finish loading" text |
| Keys | slot id = block id, so React never remounts a block that is updated |

`EnvelopeStream.feed(chunk)` turns a growing reply into these events; the result is identical for any chunking (tested down to single characters), and a text-only reply yields exactly one text block (the fast path: no parser work beyond scanning for the fence marker).

**Transport reality:** chat replies reach the browser as finished messages by polling, so `Chat.tsx` renders stored documents; the event reducer and envelope are ready for a streaming gateway but are not connected to a live partial-text source in this build.
