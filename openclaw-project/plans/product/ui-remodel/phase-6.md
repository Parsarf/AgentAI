# UI remodel, phase 6

## What was built
- **Settings in the frame** (`lumina/src/pages/Settings.tsx`): sections in the context column (a vertical tab list: arrows up/down and left/right, Home, End), each with an address (`/settings/<section>`; the older `?tab=` and names like `memory` still land in the right section). Integrations is a section (`/integrations` redirects there). Appearance: reduce motion, compact layout (density, also Shift+D and the command bar), and **contrast: like this device, normal, more contrast** (`state/settings.tsx` sets `data-contrast`; with no choice the theme follows the system's "more contrast").
- **High-contrast theme** from the phase 1 generator (contrast 1.7): text at least 7:1 on every surface step, stronger hairlines.
- **Phone finished**: every page checked at 390 px — one zone at a time, the bottom bar, sheets for the rest, no sideways scrolling, controls raised to 44 px under 600 px (`frame.css`, "Phone"), the Calendar opens on the day view.
- **Chat history and the live view in the frame**: History has the chats column as its context; the live view keeps its own layout inside the canvas.
- **The old layout is gone**: `Sidebar.tsx` (+ test), the right rail (phase 2), the old dock (phase 2), the Tasks page and the Automations placeholder (phase 5), the `old()` page wrapper, the top bar, and 140 dead rules of `styles/app.css` (the shell grid, sidebar, top bar, rail, drawers, old Home cards, old activity feed). There is no `ui_v2` switch: none was shipped (see `architecture.md`).
- **DESIGN.md** describes the frame, the zones and width classes, the primitives, the token generator, the selection-aware assistant, the shortcut registry and the accessibility rules of this project. `AGENTS.md` and `platform/UI_CONTRACT.md` updated for the new addresses.

## Checked
- `ci/run.sh all`: all 8 parts passed (198 s). Settings tests updated for the deliberate change (router, sections as addresses, a test for contrast and for direct section links); the Safety test now finds its button in the rail.
- Every page at 390, 820, 1280 and 1600 px with an automatic check (`/_w` harness): no page scrolls sideways at any width; one level-one heading per page (fixed: Home's and Chat's greetings, Activity's record title); phone targets of at least 44 px, except (a) a thread's checkbox, whose 44 px label is the target, (b) calendar events, whose height is their duration (WCAG 2.5.8 "essential"), (c) links inside the assistant's own generated cards.
- Real browser: Settings at 1563 px in normal and more contrast (`screens/after-settings-1563.jpg`, `screens/after-settings-more-contrast.jpg`).
- WCAG 2.2 AA in the layout: target size (24 px everywhere, 44 px on a phone), focus not obscured (sheets lie above the page and trap focus; sticky toolbars sit above content, never over a focused control inside it), dragging alternatives (zone edges: keyboard and "Narrower / Wider"; files: "Folder of …"; day ranges: Shift with the arrows).

## Measured
### Production (getlumina.pro, 2026-11-16, Chrome over a ~130 ms link, the owner's account with a mailbox still filling)
- Deployed `5ac1e18` (pull request #53, with #52); the live acceptance passed. The hub sync timer was replaced by the long-running service (#52's step); its first fill was running (mail 300 items in the first minutes, one calendar filled with 225 events).
- Search (`/v1/search`, five queries): 6-11 ms on the server; about 140 ms round trip from the browser. Target under 200 ms: met.
- Inbox: the first rows came 484 ms after the click, because the list waited for the accounts overview before asking for threads (two round trips in a row). Fixed in a follow-up (the list asks for every account's mail at once until the customer narrows them; one round trip fewer) and measured again below.
- Opening a thread: headers 29 ms, body 303 ms; the next thread, fetched ahead, 40 ms.
- After the follow-up (#54, deployed `fbb164c`): Inbox first rows 349-419 ms (three runs). The rest is the server: every authenticated API call takes about 120 ms on this host (even `/v1/hub/pulse`, which reads one row; `/readyz` answers in 27 ms), and the thread list takes 110-300 ms while the mailbox's first fill writes to the same database. **The 300 ms target is not met yet**; the next step is server-side (the per-request cost of the account API, and the list query during a fill), outside this remodel.

## Decisions taken
- The contrast setting has three states (device, normal, more) so the system preference is honoured by default and can still be overridden either way.
- Settings sections stay a tab list (in the column) rather than links, so screen readers keep announcing "tab, 3 of 6".

## What did not change
- All colours at normal contrast are the old values (tested). Before and after screenshots of each page are in `screens/`.

## Known gaps
- The assistant's generated cards (charts, tables) keep their own control sizes on a phone.
- A connection's grants and an organization member still open in their own sheets rather than in the Settings inspector.
