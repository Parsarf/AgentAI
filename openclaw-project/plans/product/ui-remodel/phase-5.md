# UI remodel, phase 5

## What was built
- **Home is Today** (`lumina/src/pages/Home.tsx`): the greeting with a smaller orb (48 px) and the prompt first; the four starters (search the web, build and code, analyze data, automate) kept as one-tap chips under it; then five tiles, each from live data and each opening its place: next meetings (upcoming, not cancelled, today's count), mail that needs you (unread inbox count, newest four), work running and waiting on you (needs-you first), recent files (newest four), this period's spending (used, limit, left). Every tile loads on its own; a source that is off says so in one line, one not connected says how to connect it, an empty one says "Nothing today", a failing one says it could not be loaded and offers "Try again".
- **Activity is one table** (`lumina/src/pages/Activity.tsx`): every task, approval, question, plan approval and goal; needs-you first, then in progress, then finished; sortable columns (what, kind, state, steps, started). Context: filters by state (everything, needs you, in progress, done, not confirmed, partly done or blocked, failed, stopped) and by kind, kept in the address. Inspector: the item's record with its controls (stop, pause, resume, retry, goals), its permission prompts, and now also questions, change and plan approvals (the old record only named them; they were answered in the old list). Page commands for the command bar.
- Old addresses redirect: `/tasks` → `/activity`, `/tasks/<id>` → `/activity/<id>`, `/automations` → `/activity`. The old Tasks page and the Automations placeholder are gone (the right rail went in phase 2). Links across the app point at `/activity`.

## Checked
- `pages/Home.test.tsx` (new): prompt first, live data from every source with links to each place, one failing tile degrades alone, off and not-connected wording. `pages/Activity.test.tsx`: the old list tests rewritten for the table (order, state and kind filters, approvals and questions answered in the item), the record tests unchanged apart from the address; `pages/Live.test.tsx` now expects `/activity`.
- Real browser: Home at 1563 and 390 px, Activity with an item open at 1563 px (screens `after-home-1563.jpg`, `after-home-390.png`, `after-activity-table.png`). Fixed while looking: the table heading covered the first row; shortcut chips showed inside the phone's bottom bar.

## Measured (local mock build)
- Home after a click from Files: prompt 28 ms; tiles ready at 28 (work), 37 (files, spending), 47 (meetings), 51 ms (mail).

## Known gaps
- Schedules and automations are not listed: the schedule engine is still switched off for customers; the filters say so.
