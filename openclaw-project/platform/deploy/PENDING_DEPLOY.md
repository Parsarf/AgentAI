# NOTE FOR WHOEVER DEPLOYS NEXT (read this before you deploy)

**Merged to `main` but NOT deployed** (written 2026-11-01 by the agent that built them, at the owner's request: "merge them but don't deploy; the other agent deploys them when it next deploys").
At the time of writing the server runs `1ff1ef5`; `main` is `1e8ed54` (or later). Deploying `main` deploys all three; there is nothing special to do for them. Automatic deploys were switched off (`AUTO_DEPLOY_ENABLED=false`) while these were merged, then switched back on, so **the next merge to `main` that passes CI deploys them by itself**, and so does Actions -> Deploy to server (dry run first).

| PR | What | Files you will see in the deploy |
|---|---|---|
| #8 | The browser run waits for the customer at a sign-in, password or "verify you are human" stop and carries on afterwards (state `paused` + `needs_you`; "I'm done, continue" in the Live view; the page moving on also resumes it). Payment pages and consequential buttons still end the run. | `browse/loop.py`, `browse/service.py`, `accounts/browse.py`, `lumina/src/pages/Live.tsx`, `lib/live.ts` |
| #9 | New assistant block `location_request` (Share my location, or a typed ZIP / city / address), a form with one `location` field. | `lumina/src/gen/*`, `genui/gen_registry.json` |
| #10 | An answer given in a UI component is no longer a chat bubble; the component stays locked with it (server keeps `answered` / `chosen` / `values`; the chat message row is marked in `chat_messages.native_message_id` as `ui-answer:<request id>`; `messages()` reports `ui_answer`). No schema change. | `chat.py`, `genui/artifacts.py`, `lumina/src/pages/Chat.tsx`, `gen/components/{cards,forms,context}.tsx` |

## Before you deploy
* A real deploy restarts `agentai-cell-bridge`, `agentai-browse`, `agentai-tool-relay`, `agentai-request-worker`. A browser task that is running at that moment is cut off, so deploy when none is running (the owner's own tests count).
* If you released any of the files above by hand (`push-release.py`), the deploy guard refuses (exit 30) and lists them; commit them to `main` first, or use "overwrite manual changes" only after checking the listed files are committed versions.
* Do not commit the owner's untracked `docs/plan-history/` or `output/reports/`.

## After you deploy: what to check (none of it has been seen on the live site yet; only automated tests ran)
1. Services active, `/var/lib/agentai-deploy/last` is the new commit, `https://getlumina.pro/app/` answers.
2. #8: start a browser task at a site that shows a sign-in page. The Live view should say "Lumina needs your help" with an "I'm done, continue" button; after signing in the task should carry on. Trace events: `handoff_wait`, `handoff_done`.
3. #9 and #10 reach an assistant only at its **next start** (the block catalog is written when the cell starts). Ask for something that needs a location ("coffee near me"). Answer the box: no user bubble should appear, the box should stay on screen locked, and the assistant should answer using it. Reload: still locked.
4. Chats answered before this deploy keep their old bubbles (nothing was marked then).

## Undo
Supervisor tree link and app tree rollback are printed at the end of every deploy log; see `AUTO_DEPLOY.md`.

When this is deployed, delete this file (or replace it with the next note) in the same PR that you merge.
