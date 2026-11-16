# UI remodel, phase 1

## What was built
- **Generated colour tokens** (decision 12): `lumina/scripts/tokens/generate.mjs` + `oklch.mjs` make every theme colour from a base (`#060608`), an accent (`#7455ff`) and a contrast value, in OKLCH. Output `src/styles/theme.css` (committed; `--check` runs in `npm run build`). Normal contrast reproduces the old hand-set values exactly (OKLab distance 0 for all 19); a high-contrast set (contrast 1.7) is generated for phase 6. `src/styles/theme.test.ts`: the old values, WCAG AA on every surface step (7:1 at more contrast, including a hovered row), accent 3:1, surface order.
- **The frame** (decisions 1, 13, 14): `components/frame/` — `layout.ts` (width classes, docking, canvas minimum, widths), `FrameProvider.tsx`, `Workspace.tsx`, `Split.tsx`, `List.tsx` (virtualized), `parts.tsx` (`Toolbar`, `EmptyState`, `Inspector`, `Table`), `ui/Sheet.tsx` (now the one sheet: side, portal, focus trap, focus return), `styles/frame.css`. Pages declare zones through `<Workspace>`; the frame decides docked or sheet.
- **Rail and context column** (decisions 2, 3): `components/frame/Nav.tsx` — rail (Home, Chat; Inbox, Calendar, Files; Activity with the waiting count; Search, Assistant, Safety, Settings, account), phone bottom bar with More sheet. The top bar is gone: titles are in the canvas toolbar, the bell is the Activity count, motion moved to the account menu, search stays on Ctrl+K and the rail.
- **Chat in the frame** (1.4): context = `ChatsColumn.tsx` (new chat, title search, Enter searches every message, grouped by project when there are several); canvas = thread and composer, unchanged; inspector = `ChatInspector.tsx` (working now, tasks, files, plans of this chat). Chat history is reached from the column ("All chats and archive").
- Pages not moved yet render in the canvas in their old form (`old()` in `App.tsx`).
- Local tooling: `dev-mock-hub.mjs` (mail, calendar, files data, 100,000 threads), `/_w?w=<px>&p=<path>` width harness in `dev-mock.mjs`, `gen/FrameStress.tsx` at `/app/frame-stress/<kind>`.

## Checked
- `ci/run.sh lumina` green (tsc, 599 web tests, design check, theme check, build).
- Stress test: thread, list with detail, calendar grid, file tiles, settings form, dashboard, long table, each at 390, 820, 1280, 1600 px, with an automatic check (no sideways page scroll, canvas at or above its minimum, toolbar present, rail or bottom bar present). All 28 passed with no page-specific exception. Screens: `screens/stress-list-1280.png`, `screens/stress-table-820.png`.
- Chat looked at in a real browser at 1600, 1280, 820 and 390 px; keyboard: skip link, rail, Ctrl+B for the column, separators resize with arrows/Home/End, sheets trap focus and return it. Reduced motion: the frame adds no animation that the existing `data-motion` rule does not remove.
- Before screenshots of the old app: `screens/before-*.jpg`.

## Measured (local mock build, Chrome, time to the second frame after the click)
- Fold/unfold the context column: 27-80 ms (target < 100 ms: met).
- Move between places from the rail: 60-129 ms (Files 129 ms: it loads its catalogue; others under 100).
- Open another chat: 200 ms (three requests before the thread shows). Gap: the thread could show its title and cached messages first.

## Decisions taken
- **No `ui_v2` switch**: every phase ships in one deploy and phase 6 deletes the switch, so it would exist in no deployed version (see `architecture.md`). The old app's look was compared with screenshots of the pre-remodel build.
- The page scrolls (not the canvas): Chat's stick-to-bottom and sticky composer keep working untouched.
- Default zone widths 248 / 380 / 360 px so that all zones dock from exactly 1500 px with the canvas over its 440 px minimum.
- The globe is drawn inside Home's canvas (`backdrop` prop) instead of behind the whole app: the canvas is an opaque panel now.
- `TaskStrip` resets its "Details" fold while rendering instead of in an effect (a fast first click was being undone).

## What did not change
- Every colour is the old value (tested). The composer, bubbles, task strips, orbs, menus and buttons are untouched; the chrome is the old near-black with the violet dot moved to the rail's left edge.

## Known gaps
- The assistant zone exists in the frame but is filled in phase 2 (the rail button shows on pages that allow it).
- Opening a chat takes 200 ms locally before content.
