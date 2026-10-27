# Testing: strategy, what was run, results, gaps

Run on 2026-10-27 on the local checkout (branch `product-phases-6-11`, uncommitted).

## Commands and results

| Command (from) | Result |
|---|---|
| `npx tsc --noEmit` (lumina) | clean |
| `node scripts/check-design.mjs` (lumina) | no hard-coded colours |
| `npx vitest run` (lumina), whole suite | **306 passed**, 36 files |
| `npx vitest run src/gen` (lumina), the new tests | **89 passed**, 3 files (`gen.test.ts` 56, `gen.components.test.tsx` 31, `export.test.ts` 2) |
| `npm run build` (lumina) | built; generative UI is in lazy chunks |
| `python3 -m unittest tests.test_gen_document tests.test_display tests.test_genui tests.test_cell_config tests.test_card_images tests.test_chat` (platform) | **169 passed** |
| `python3 -m unittest discover -s tests -t .` (platform), whole suite | 996 run, 2 skipped, **1 error**: `tests.test_vault` cannot import `cryptography` (not installed in this Python; unrelated to this work, not investigated further) |
| Django `accounts` tests | **not run**: Django is not installed in this environment. The `/v1/conversations/{id}/blocks` route is unchanged and the new kind passes through `BlockStore.list` (tested at that level). |

## What the tests cover

- **Registry and manifest** (`gen.test.ts`): unique ids, every implemented entry has a real renderer, nothing planned/unsupported/adapter is offered, the model catalog lists only offered components and stays under a size budget, a renderer exists for exactly the registry keys.
- **Schemas and variants**: every fixture block validates; 14 refusal cases (HTML, unknown props, `javascript:`, credentials in URLs, bad variant, unknown type, bidi override, absolute/traversal/remote asset refs, too many series, stacked with one series); nesting bounds; action allowlist; presentation plan is advisory and carries no data.
- **Documents and migration**: order kept, one bad block does not hide others, fallback text kept, missing `dataRef`, duplicate ids, block cap, version lift and refusal, plain-text migration, fence splitting, JSON Lines.
- **Streaming**: prose into a stable block, widget placeholder then mount, invalid block fallback, duplicates, out-of-order hold, other-response events, in-place update, error and retry, pending degrade; the envelope scanner gives the same result for any chunking including one character at a time, never leaks fence text, and a text-only reply is one block.
- **Actions**: refusal of unknown kinds, live-state authorisation (approve only when awaiting, retry only when failed), confirm / decline, duplicate, failure releases the key, rate limit, navigation allowlist, local target must exist, destructive forces confirm.
- **Components (jsdom + Testing Library)**: every offered type renders without a fallback; no raw HTML or remote images from Markdown, unsafe links dropped; error boundary contains a throwing renderer; local sort / search / paging / tabs (keyboard) / accordion / legend with **no network call**; chart summary and data-table alternative; form validation, conditional fields, exact message sent; approval round trip (dialog, one host call, done), cancel, states pending / approved / skipped / failed / expired, failed host call, follow-up sends exact words once; agent widgets read provider state and refuse ids not in the chat.
- **Accessibility checks that are automated**: region/button/input names, progressbar values, alert role, status never colour only, reduced-motion / focus-visible / touch-target rules present in the CSS.
- **Server** (`test_gen_document.py`, 23 tests): browser fixtures (valid and invalid) replayed through the Python validator; unsafe input never stored; code may contain `<`; only offered components; datasets pruned; bounds; extraction (JSON, JSON Lines, unfinished, oversized, one per reply); presentation plan validation; **stored end to end** via the real worker (document stored once, fence removed from the message, unsafe document stores nothing, plain reply makes no block, other tenant cannot list it); the assistant rules mention only what exists.
- **JEV** (`test_display.py`, 6 new): one call carries both questions; old answers without the second one still work; unsure / none / broken hint means no hint; switch off, slow or failing JEV means no plan and no error; short replies cost nothing; the plan is stored beside the layout choice.
- **Drift guards**: `gen_registry.json`, `gen_parity.json` and `component-catalog.md` are generated; `export.test.ts` fails when they are stale (`GEN_WRITE=1 npx vitest run src/gen/export.test.ts` regenerates).

## Manual checks

The gallery (`/app/gen-gallery`) was loaded from the local mock server in the in-app browser: all 40 blocks of "Every offered block" rendered, no fallback shown, no console error; desktop and 375 px width looked right and the page did not scroll sideways (tables scroll inside their own region). One cosmetic bug (status pill stretching across a card) was found and fixed.

## Not done (known gaps)

- **No visual-regression images.** The repo has no screenshot-diff tooling; the gallery renders every offered block in normal / loading / empty / error states and three densities for manual and future automated comparison.
- **No machine accessibility audit** (no axe), no screen-reader run, no machine contrast calculation (relies on the existing token contrast notes), RTL checked only as text rendering in jsdom, no real-device touch test.
- **No live end-to-end run** with the real model, real JEV, or a deployed server. Whether the model writes good `lumina-doc` fences from the new rules is **unverified**; only the server's handling of fences is tested.
- **Streaming UI not wired to Chat** (no partial-text transport); the reducer and envelope are tested in isolation.
- The Django layer and `cryptography` tests could not run here.

## Measurements (this machine; jsdom timings are not browser timings)

| What | Value |
|---|---|
| Parse + validate the 6-block sample conversation | 0.3 ms |
| Parse + validate all 38 offered blocks | 0.9 ms |
| Render the sample conversation in jsdom | ~8 ms |
| Envelope scan of a 2,000-character text reply, one character at a time | ~10 ms total |
| Generative UI code (lazy, loaded only when a reply has a document or the gallery opens) | Renderer chunk 86.7 kB (26.9 kB gzip) + 4.0 kB gzip CSS; Gallery 13.4 kB; bridge 1.6 kB. The main chunk (763.7 kB) was not compared with a pre-change baseline. |
| Always-on token overhead for the assistant | the new rules section ≈ 1,100 tokens (characters / 4 estimate; the compact catalog alone ≈ 625). The long catalog (≈ 1,450) is not injected. |
| Generated props cost | sample 6-block document ≈ 2.1 KB of JSON (≈ 530 tokens estimated) |
| Extra model calls | text-only reply: 0. Composed reply: 0 (same inference). JEV: 0 extra calls, one extra question on a call that already exists. |
| First-token latency, first-widget latency | **not measured** (needs the live gateway). By construction prose is not delayed by the document: it precedes the fence. A composed reply costs more output tokens than text alone; whether that is cheaper or dearer than a follow-up turn depends on the task. |
