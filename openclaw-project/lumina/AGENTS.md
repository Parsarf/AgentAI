# Lumina UI requirements

**Visual design:** read `DESIGN.md` before any UI change. Colours, radii, type and spacing come from the tokens in `src/styles/tokens.css`; use the shared components in `src/styles/ui.css` and `src/components/ui/` (Menu, Toggle) instead of writing new buttons, menus or switches. `npm run check:design` (part of `npm run build`) rejects hardcoded colours. Do not build features the product does not have just because a mock shows them.

Messages and assistant thinking indicators must size to their content. Spare pane height belongs
between the transcript and composer, never inside message rows. Any grid filling
the chat pane must pack its rows at the start; nested turns must not stretch their
children. Never reintroduce a Working card in chat. A task is shown under the message that asked for it by `components/work/TaskStrip.tsx`: not a card, a left-aligned 48px orb with the server's status words (one line per thing when several run at once), prompts that need the customer right there, and after it ends a one-line record (how it ended, whether that was confirmed, counts) with the detail folding out below through Details. A plain answer that used no tools shows nothing under it. Stop belongs in the composer, replacing Send while a task is active.

**Task state has one source.** What a task is doing, what it needs, how it ended and what can be done to it are computed on the server (`platform/agentai_platform/work.py`) and reach every screen through `state/work.tsx` (`useWork`, `useTask`), which is pushed over the stream and falls back to polling by itself (`lib/workClient.ts`). Do not derive status from request rows or raw events in a component, do not add a timer that asks about tasks, and do not word a status yourself: render `task.label`. "The run finished" and "the result was confirmed" are separate facts (`outcome`, `verification`) and must stay worded apart. The assistant's own checklist is always labelled as its report. Never post a message in the customer's name (a permission decision is recorded by the server as a `system` line).

Active conversation routes must not render the decorative globe. On screens that
show it, use the static fallback only while loading, after a rendering failure, or
when motion is reduced. Never render the fallback underneath a loaded globe.

For chat layout changes, run the UI tests and build, then inspect the rendered page
at desktop and mobile widths with: one short message while working, completed
reply, long wrapped message, and multiple turns. Check both motion settings.
Confirm a short bubble stays one line tall plus padding, thinking indicators have no
unused vertical space, and the composer and messages do not overlap. jsdom does
not perform real layout, so passing unit tests alone is insufficient visual QA.

The real-browser fixture is `tests/preview_chat.py` (instructions in its docstring).
It runs `tests/browser-layout.js` against the production bundle. For each fixture
and viewport, require `document.documentElement.dataset.layoutCheck === 'passed'`;
inspect `dataset.layoutFailures` if it fails. Keep these checks when editing chat CSS.

Orb animations are listed in `src/lib/orbs.ts`; which one shows is decided from the server's task state by `orbFor` in `src/lib/work.ts` (only a task that is really doing something gets a moving orb). Map actual task state, never
simulate progress by cycling animations on a timer. Finished tool calls must stop
showing their old activity; completed replies remove the indicator. Keep terminal
errors visible without a looping orb. Preserve reduced-motion support.

Thinking orbs run at 55% of the library preset speed and blend states over 600ms.
Keep their motion timeline continuous across state changes, preserve the displayed
frame if a transition is interrupted, and skip blends when motion is reduced.

The transcript has a bounded width with `minmax(0, 1fr)` grid tracks. Prose and
inline code wrap naturally (long tokens must not widen the page); fenced code
preserves lines and scrolls horizontally within a keyboard-focusable code box.
Wide tables scroll within their own container. Never add horizontal scrolling to
ordinary paragraphs. Recognized read-only JSON cards are schema-validated before
rendering; malformed data and code examples remain literal, locally scrollable code.
Verify charts plus very long code lines, prose, URLs, and tables at mobile/desktop
widths, including the visible scrollbar and ability to reach the end of a code line.

A task's workspace (`pages/Live.tsx`, `/live/:id`) is the same view while it runs and afterwards as its record; `/live` alone is not a destination (it goes to the open task, or to Activity). Activity (`pages/Tasks.tsx`) lists what needs the customer, what is in progress and finished work, and `/tasks/:id` is a task's record. Show observable tool activity and reported output, never invented
reasoning or simulated shell output. Browser takeover is enabled only after the
backend confirms pause/handoff and takeover. Sensitive text is masked by default,
cleared after submission, and never stored in local/session storage. Browser input
must be serialized before returning control. Keep task details bounded on mobile.

To look at all of it in a real browser on the real state code (no assistant: a scripted run, in the fixture only): `npm run build && ../platform/.venv/bin/python tests/preview_work.py` (docstring has the chats; `PREVIEW_PUSH=0` shows the polling fallback). It loads the same layout assertions as `tests/preview_chat.py`.
