# Security and privacy

Model output is untrusted. The model writes data and props only.

## What cannot get through

| Risk | Control |
|---|---|
| Script, HTML, CSS | Schemas are strict (unknown keys rejected); text refuses HTML-looking markup, control characters and bidi overrides; Markdown skips raw HTML; there is no `style`/`class`/`src` prop; variants are enums mapped to fixed classes. |
| Unsafe links | Only `http(s)` without credentials, ≤ 500 chars, opened with `rel="noopener noreferrer nofollow"`. `javascript:`, `data:`, `file:` and protocol-relative links are refused (both validators). |
| Data leaving through images | **No remote image is ever loaded** (a URL could carry the conversation out, and loading it tells a third party the reader is there). Markdown images render as their alt text. `image`/`gallery` accept only `file:<relative path>` in the customer's own files and are not offered until a host resolver exists. |
| Path traversal | `file:`/download paths must be relative, with no `..`, `.`, empty segment, backslash, scheme or control character. |
| Internal navigation | Only `/chat /tasks /files /live /history /calendar /settings` (+ sub-paths); no `//host`, no `..`. |
| Oversized or deep input | 48 KB, 24 blocks, 60 nested, depth 3, text 8,000 chars, datasets 500 rows. |
| Prompt injection into the next turn | A button or follow-up sends exactly the words the reader can see, as the reader's own message, after the same confirmation as before; form submissions are assembled by the browser from the reader's answers, not by the model. |
| Fabricated agent state | Agent blocks hold ids only. State, steps and results are read from Lumina's own records; an id that is not in this chat shows "not part of this chat". |
| Fabricated data | Prompted against (real results only), but **not technically preventable**: the server cannot tell a true number from an invented one. Metric and chart blocks can show a `source` text; nothing verifies it. |

## Actions

`local.*` act on a block that exists in the same response (the target id is checked), in the browser only. Everything else goes through `Dispatcher`:

1. **Schema**: kind must be in the allowlist and parameters must validate (strict).
2. **Authorisation against live state, never the document**: approve / skip only while the server's block list says the phase is `awaiting_approval`; retry only for a `failed` phase; the id must belong to a plan in this chat. The server re-checks ownership and state (`runner.act`: tenant-scoped, `Conflict` on a wrong state) and rate-limits (`block.action` 60 per hour).
3. **Confirmation** for approve, skip and retry (and any `destructive` button): the person sees what will happen; Escape or Cancel does nothing.
4. **Idempotency**: a deterministic key per (scope, action); a repeat is `duplicate`; the key is claimed before the call and released on failure so a retry is possible. `send` passes the key to the existing send endpoint.
5. **Rate limit**: 8 consequential actions per minute per dispatcher (client side; the server's limits are the real ones).
6. **Audit**: every attempt (done, refused, declined, failed, duplicate, rate-limited) is reported to `host.audit`. In Chat this is a debug log only. The durable record of approvals is the server's own (`plan_phase_runs.approved_epoch`, request history); there is **no new server-side audit table**.
- CSRF and session authentication come from the existing `api()` client and endpoint decorators; the new code adds no endpoint.
- `file.download` exists in the schema and dispatcher but the chat host throws "not wired", the registry does not offer it and the server rejects it.

## Server side

`document.py` validates before anything is stored and re-validates nothing it did not store; a fence that fails is removed and the prose stays. Another account's blocks are not reachable (`BlockStore.list` is tenant-scoped; covered by a test). The assistant rules text is generated from the registry, so it cannot advertise a component the server would reject.

## Known gaps

- The server's rules that JSON Schema cannot express are written twice (TS and Python) and kept in step by shared fixtures, not by construction.
- No server-side audit trail for rejected action attempts.
- Client-side action rate limit and idempotency reset on page reload; the server's behaviour (409 on a wrong state, per-hour limit) is what protects against replays.
- A `text` block's Markdown can contain a link whose visible label differs from its address; the address is always shown by the browser on hover and the link opens in a new tab, but the label is not checked.
