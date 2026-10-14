# Lumina UI requirements

Messages and assistant thinking indicators must size to their content. Spare pane height belongs
between the transcript and composer, never inside message rows. Any grid filling
the chat pane must pack its rows at the start; nested turns must not stretch their
children. Never reintroduce a Working card in chat. Pending replies use a left-aligned 48px thinking orb and short state label; Stop and Activity belong in the header.

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

Orb state definitions live in `src/lib/orbs.ts`. Map actual task/event state, never
simulate progress by cycling animations on a timer. Finished tool calls must stop
showing their old activity; completed replies remove the indicator. Keep terminal
errors visible without a looping orb. Preserve reduced-motion support.

Thinking orbs run at 55% of the library preset speed and blend states over 600ms.
Keep their motion timeline continuous across state changes, preserve the displayed
frame if a transition is interrupted, and skip blends when motion is reduced.
