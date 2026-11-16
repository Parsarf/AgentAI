# UI remodel, phase 2

## What was built
- **One assistant panel** for every page but Chat: `lumina/src/components/frame/Assistant.tsx` (`AssistantProvider`, `useSelection`, `AssistantZone`). Docked at the right from 1500 px, a sheet below, from the rail button, Ctrl/Cmd+J, the phone's More sheet or the command bar. It keeps the old dock's conversation (same storage key), so nothing is lost.
- **It knows the selection**: pages call `useSelection({ looking, words, actions })` with ids only — a mail thread or the mail list (Inbox), an event or a range of days (Calendar), a file or a folder (Files), a task (Activity), or the page. The panel says "Looking at: …".
- **Server**: `POST /v1/assistant/ask` (`platform/accounts/assistant.py`), checked by `platform/agentai_platform/selection.py` (files, folders, tasks, pages against the account's own rows; mail and calendar through `hub.looking_at`, only while that switch is on). `chat_driver.dashboard_note` words file, folder, task and page selections, every name scrubbed with `neutralize`. Route table row and OpenAPI entry added. `/v1/hub/ask` stays for old clients.
- **Structured controls**: one-tap actions supplied by each page for what is selected; after an action marked as a draft ("Draft a reply"), "Shorter / Longer / More formal / Simpler" as single steps. No generic suggestions: with nothing selected only the page's own actions, or none.
- **Work in progress has one home**: each request of the panel's chat shows its `TaskStrip` (steps, approvals and questions, the same component as Chat and Activity). Stop replaces Send while a task runs. After 30 seconds: "Keep it going in the background", followed in Activity, with a notice when it finishes or needs a decision.
- "Open in Chat" opens the same conversation full size.
- Removed: `components/hub/Dock.tsx` (+ test), `components/Rail.tsx` (the old right rail, + test).

## Checked
- `accounts.test_hub` (56 tests, including the new panel test: selection kinds, another account's ids dropped, switch off drops mail selections, bad input 400, another account's chat 404). The planted-instruction cases in `tests/test_hub.py` are unchanged and pass in CI; a planted file name ("Ignore previous instructions…") is scrubbed in the note.
- `components/frame/Assistant.test.tsx` (8): no requests while closed, selection words and ids, Open in Chat, draft changes as single messages, none after an ordinary answer, Stop and background, refusal keeps the text, a gone chat starts fresh, sheet below 1500 px.
- Real browser: Inbox at 1563 px with all five zones docked and the panel naming the open thread.

## Measured
- Opening the panel is a local state change (no request until it is open): under one frame.

## Decisions taken
- One general route instead of widening `/v1/hub/ask`: the panel must work when the mail switch is off.
- The draft changes are offered in the visit that asked for the draft (the server does not record which answers were drafts).

## Known gaps
- A finished background task is announced in the open app only; there is no notification outside it.
