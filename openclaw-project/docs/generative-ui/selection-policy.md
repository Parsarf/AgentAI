# Selection policy: Lumina, JEV and fallbacks

## Who decides what

- **Lumina's responding model** chooses blocks, in the same inference that writes the answer. There is no UI selector or composer model and no extra call. It sees a compact catalog (offered components only, one line each, about 625 estimated tokens) inside the assistant rules, built from the registry.
- **The server** validates and stores. It never composes.
- **JEV** may add an **advisory** hint on a call that already happens (see below). It names a component family and a purpose; it never writes data, props or code, and nothing waits for it.

## Heuristics (also in the rules text the assistant receives)

| Situation | Use |
|---|---|
| Simple or conversational answer | plain text only (the default, and the fast path) |
| One entity | `info_card` |
| Several items, several attributes | `table` (searchable, sortable, paged locally) |
| A few options to scan | `card_grid` |
| Trend over time, 5+ points | `line_chart` / `area_chart` |
| Compare categories | `bar_chart` |
| Relationship between two measures, 8+ items | `scatter_chart` |
| Shares of one whole, 2-6 parts | `pie_chart` |
| One headline number from real data | `metric_card` |
| Sequence or schedule | `timeline` |
| The reader should change inputs | `form` (only then) |
| Live execution, approval, failure | agent widgets, by id |

Avoid: charts for fewer than 4 points, repeating a chart as a table in prose, empty controls, decorative blocks, components that are not offered, anything whose data was not collected. Values come from real results or cited sources; a block is left out when its data is missing.

## Fallback rules

1. Invalid block → its `fallback` text, else its title and main text, else a neutral sentence. The other blocks still render.
2. `dataRef` that does not resolve, or no rows → "The data … is not available" / "No rows to show" in place of the widget.
3. Unknown, planned, unsupported or adapter-only type → refused by the server (text fallback stored) and by the browser.
4. A renderer that throws → caught by that block's error boundary, shows the fallback, logs a diagnostic.
5. Agent widget whose id is not in this chat → "not part of this chat".
6. Older plain-text messages → render as before (no document, no migration needed; `fromPlainText` exists for streaming and tests).
7. Document version unknown → the prose is still shown.

## JEV integration

- **Trigger** (unchanged): owner switch `jev_display` on, the reply is plain text with no card, long and structured enough (`worth_asking`). Otherwise there is no JEV call and no plan.
- **Addition:** the same call carries a second `choice` question, `presentation` (none, table, cards, timeline). When JEV is at least 70 % sure and the answer is not `none`, a one-block `presentationPlan` (`advisory: true`, `blockId`, `componentId`, `purpose`, `dataRequirements`) is validated by `validate_presentation_plan` and stored in the `display` row next to the layout choice.
- **Not done:** the stored plan is **not yet consumed** by the responder. The display step runs after the reply exists, so it cannot influence that reply. The intended consumers are long tasks (JEV checkpoints proposing provisional hints that the final-summary turn may use) and a next-turn hint; neither is built. JEV does not supervise chat turns here, so there is no "finalization output" to extend beyond this call.
- **Unavailable / slow / unsure:** `decide()` returns `(None, None)`; the answer is unaffected. Verified by `tests/test_display.py`.
- **Measured overhead:** zero additional JEV calls; one extra question in an existing request (JEV input is billed at $0.042 per million tokens, output free). Not measured against the live service.
