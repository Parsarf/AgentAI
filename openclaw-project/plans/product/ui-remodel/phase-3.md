# UI remodel, phase 3 — and the report to the owner

## What was built
- **Inbox** (`pages/Inbox.tsx`): context = accounts, mailboxes, filters, the providers' own labels; canvas = the thread list, virtualized (`components/frame/List.tsx`), loading the next page by itself near the end; inspector = the open thread, or "full" reading view (thread in place of the list, remembered). Both densities (row 100 px comfortable, 64 px compact without the preview line). Multi-select with checkboxes, Shift-click ranges and `x` (selects only). Opening shows the headers at once and the body after; the next thread down is fetched ahead. Live updates keep the reader's rows in place.
- **Calendar** (`pages/CalendarPage.tsx`): context = a small month for jumping, accounts and calendars with colours; canvas = day, week, month, agenda; inspector = the event. Day ranges by dragging across day headings or from the keyboard (arrows move, Shift extends, Esc clears): they tell the assistant "these days". The grid opens at the current hour; the now line moves every minute. A phone opens on the day view.
- **Files** (`pages/Files.tsx`): context = the folder tree of each project (drop a file on a folder to move it); canvas = list or grid (remembered), sortable (newest, oldest, name, size, kind); inspector = preview, versions, where it came from, and the organize controls. Moving by drag and by the "Folder of …" control.
- `styles/hub.css` lost its page grids, the old dock and the narrow-screen zone rules; it keeps only mail and calendar content.

## Checked
- Existing behaviour tests: Inbox 21, Calendar 9, Files 7 pass in the frame. Changed on purpose (each says why in the test): Inbox pages by itself instead of a "Show more" button (2 tests), and the empty "Select a thread" pane is gone (the inspector exists only while a thread is open).
- The neutrality test (no provider named in mail and calendar screens) still passes; the moved files keep using `provider_label` only where the account's own words are shown.
- Real browser at 1563, 820 and 390 px (screens: `after-inbox-1563.jpg`, `after-calendar-1563.jpg`, `after-files-1563.jpg`, `after-inbox-820-sheet.png`, `after-inbox-390.png`, `after-calendar-390.png`). Fixed while looking: the toolbar shrank inside window-high canvases on a phone; the redundant back arrow in a thread sheet.

## Measured (local mock build, Chrome)
- A list of **100,000 rows**: a jump anywhere renders in 5.9 ms median, 7.1 ms p95 (one frame is 16.7 ms); continuous scrolling ran at the tab's own idle frame rate (no extra frames dropped beyond the automated tab's 25 ms baseline); the row at position 99,000 is reachable directly.
- Inbox: first rows 27 ms after the click; an opened thread's headers 10 ms, its body 119 ms (the mock adds 120 ms); the next thread, fetched ahead, 5 ms.
- The first page on the production host is measured after the deploy (phase 6 record).

## Report to the owner (before and after)
Before: `before-inbox-1600.jpg`, `before-calendar-1600.jpg`, `before-files-1600.jpg`. After: the `after-*` screens above. Same near-black surfaces and violet accent; the page title moved into each page's own toolbar; the mail list, calendar grid and files sit in one frame with the assistant beside them; lists of any size scroll smoothly.

## Known gaps
- Selecting threads does not manage mail yet (roadmap Phase 6).
