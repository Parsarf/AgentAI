# UI remodel, phase 4

## What was built
- **One shortcut registry**: `lumina/src/lib/shortcuts.ts` (key, name, group, places). The help sheet, the command bar, the rail's tooltips and the context toggle's tooltip read from it; `useFrameKeys` (in `CommandBar.tsx`) handles the frame's own keys from it.
- **Command bar** (`components/frame/CommandBar.tsx`): Ctrl/Cmd+K and `/` (except in the Inbox, where `/` searches mail). Empty: recent things (opened from the bar, then recent chats) and the actions of this page. Typing: places, settings sections and actions locally, and one server search. Actions are marked apart from things to open and show their shortcut. Results open their page (`/inbox?connection=&thread=`, `/calendar?…&event=`, `/files?open=`, `/activity/<id>`, `/chat/<id>`). No match explains itself and offers "Ask your assistant: …". A store that failed is named.
- **Page commands** (`useCommands`): Calendar (next and previous period, today, views), Files (new folder, upload, list or grid), Inbox (refresh, reading view, unread only, search mail). Each also exists as a control on its page.
- **Server**: `GET /v1/search` (`platform/accounts/search.py`): chats, tasks, files and, while mail and calendars are on, threads and events, under the person's own account, with a 0.6 s budget; a store that fails or would start late is named in `dropped`. Route table row and OpenAPI entry added.
- **Help sheet** on `?`: every shortcut of the current page, grouped, read from the registry.
- Frame shortcuts: F6 / Shift+F6 move between zones, Ctrl/Cmd+B side column, Ctrl/Cmd+J assistant, Shift+D density, `g` then a letter for each place.

## Checked
- `lib/shortcuts.test.ts`: no two shortcuts share keys in a place (and a planted clash is caught), wording, matching, places. `components/frame/CommandBar.test.tsx`: opening and closing, empty state, one request per search, opening a result, a dropped store and the assistant offer, Enter, `?` lists exactly the registry, `g a`, nothing fires while typing.
- `accounts.test_hub`: the search test (kinds, nothing of another account, a failing store named, the mail switch off).
- Nothing is reachable only by keyboard: every action in the bar exists as a control (rail, toolbar, menu).

## Measured
- Search on the production host is measured after deploy (target under 200 ms for a typical account).

## Known gaps
- Settings sections in the bar open `/settings/<section>`; the section pages arrive with phase 6.
