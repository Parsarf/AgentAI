# Phase 4 — owner Chrome checks

The owner requested manual sign-in and browser operation on 2026-09-27.
Codex handles coding and server work; the owner performs the checks below.
No Chrome automation is required. This is the owner-requested manual handoff;
owner verification does not establish the original native browser-worker
capability gate. That capability proof remains deferred.

**Owner deferred all tests on September27.** The preview is stopped. Keep this
checklist for later; no action is required now.

## Open the app

While the preview is running, open Chrome at <http://127.0.0.1:18795> on this Mac.
No account or password is needed. The preview serves the exported native-tested
source; all eight source hashes are checked before starting. It binds only to
local loopback and serves four application assets. It does not serve credentials,
repo metadata, test reports or other workspace files.

To restart from `/Users/parsa/AgentAI`:

```sh
.venv/bin/python openclaw-project/bin/phase4/serve-preview.py
```

Leave that terminal running while checking. Stop it with Ctrl+C afterward.

## Checklist

1. Add `  First  ` and then add another `First`. Both tasks appear, trimmed.
2. Submit spaces only. A visible error appears and the title field has focus.
3. Complete one task. Active and Completed each show the correct task; All
   shows both. Reload Chrome: both tasks and completion are preserved.
4. Delete just one task. The other remains. Delete the last task and check
   the empty views for All, Active and Completed.
5. Add `<img src=x onerror=alert(1)>`. It appears as literal text; no alert
   or image element appears. Do not paste scripts from unfamiliar sources.
6. Use Tab, Enter and Space to add, toggle, change filters and delete. Focus
   should be visible; report any lost focus or control that cannot be operated.
7. In Chrome DevTools, use a 360×800 viewport. Check for clipping, horizontal
   overflow and usable controls. Also check normal 1280×720 size. Save screenshots.
8. Check DevTools Console for errors. In Application → Local Storage, edit
   only `private-task-board:v1` on this preview origin to invalid JSON; reload.
   Confirm a notice appears and the invalid value is not silently replaced.
   Click “Replace saved data” only after confirming the notice; this discards
   the synthetic saved state. Report storage failures rather than marking them
   passed without checking.

Reply with which steps passed, any failure and screenshots if available.
Use synthetic tasks only; screenshots must not include passwords or tokens.
Independent ACP review and final verification remain separate requirements.

## Control UI sign-in, if needed

From this Mac's terminal, run:

```sh
cd /Users/parsa/AgentAI
.venv/bin/python openclaw-project/bin/open-control-ui.py
```

This uses the private `.env` SSH credentials, establishes a tunnel and opens
the native single-use browser handoff. Complete any pairing/sign-in prompt
yourself. Do not paste the handoff URL or tokens into chat. It uses the default
browser; choose Chrome as the default if desired. Existing saved ChatGPT login
does not need to be repeated unless an actual authentication failure is found.
