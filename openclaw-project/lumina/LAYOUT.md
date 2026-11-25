# Lumina layout contract

How every screen of the app is laid out, what may overlap, and the checks that hold it. `DESIGN.md` says how Lumina looks; this file says how it holds together
when content is longer, shorter, later or larger than expected. `AGENTS.md` makes it mandatory.

## 1. Policy

1. **Normal flow first.** Block flow, Flexbox and Grid place things; `gap` spaces them, with the `--space-*` tokens. A box grows with its content.
2. **Every flex or grid child that holds text can shrink.** `min-width: 0` on flex items, `minmax(0, 1fr)` for grid tracks. Without it a long word or a nowrap
   label widens the whole column (the default `min-width: auto` is the cause of most page-wide overflow).
3. **Text wraps or truncates on purpose.** Prose wraps (`overflow-wrap: anywhere` for user content: names, URLs, tokens). A label that must stay on one line
   ellipsizes **on a block box** (`text-overflow` does nothing on a flex or grid container: the text is then cut mid-letter) and carries its whole text in a
   `title`, an accessible name or a disclosure. Code and tables scroll inside their own box; a page never scrolls sideways.
4. **Sizes follow content.** No fixed `height` on a box that holds text; use `min-height`. Viewport heights are `dvh`, never `vh` (on a phone `vh` is taller than
   what is shown). Widths of components come from their container, never from the window (`vw`): a panel is narrow on a wide screen when zones are docked.
5. **Components decide by their own width.** A component that changes arrangement uses a container query (the composer, `MasterDetail`) or intrinsic wrapping (a
   flex row where the name claims `flex-basis: 10rem` before buttons share its line: `FileCard`), not a `@media` width. Media queries are for the frame only.
6. **One owner per scroll.** The page scrolls (Chat depends on it); side zones are sticky columns with their own scrolling; a `fill` workspace gives the canvas the
   window's height and lets one list or grid inside scroll (Inbox, Calendar). Never two tall scrolling boxes on the same axis inside each other.
7. **Stable while things arrive.** Skeletons reserve the space of what is loading; a status line replaces the previous one in place; spare height goes between
   the transcript and the composer, never into rows.
8. **Controls stay reachable.** 24 x 24 px targets everywhere, 44 px under 600 px (the `w-compact` rules in `frame.css`, which also reach portalled sheets and
   menus because the width class is on the document root). A control is never left under a bar it cannot be scrolled out of.

Out-of-flow positioning (`absolute`, `fixed`), negative margins, transforms that place a box, and `z-index` are allowed only with a reason (section 4).

## 2. Component contract

Every shared component has, in its stylesheet comment or here: how it sizes, how its content wraps or overflows, what it does when narrow, and how it stacks.

| Component | Sizes | Content | Narrow | Stacking |
|---|---|---|---|---|
| `Workspace` (`frame/Workspace.tsx`) | the frame's zones; canvas never under 440 px while a zone is docked | toolbar title ellipsizes with a `title`; tools wrap as a group | title stays beside the side-column toggle (`flex: 1 1 8rem`), tools join or wrap below | toolbar is sticky (`--z-sticky`) |
| `MasterDetail` (`.master-detail`) | fills a `fill` canvas | list and detail each scroll | container query at 820 px of canvas: one at a time | none |
| `Sheet`, `Menu`, `CommandBar` | content height, capped by the viewport | body scrolls, footer stays | sheet takes the width at the bottom | portalled layers (`--z-modal`, `--z-menu`) |
| `Composer` | the thread column | textarea grows to `min(260px, 40dvh)` then scrolls | `@container composer (max-width: 560px)`: two rows, short "Keep working" label | inside the sticky dock |
| `TaskStrip`, `Status` | content width (`justify-items: start`) | one line per thing, ellipsized with a `title` (`Doing`) | the column bounds it, never the window | none |
| `FileCard` | the column, up to 640 px | name ellipsizes with a `title` | buttons wrap below the name by intrinsic size | none |
| `Table` (`frame/parts.tsx`) | the canvas | cells wrap; a title link ellipsizes on a block box with a `title` | horizontal scroll inside `.table-wrap` | none |
| Calendar grid | the canvas (`fill`) | an event never shorter than one line; a line that does not fit is not drawn | days keep 112 px and scroll sideways | local order 1-5 inside the grid |

## 3. Stacking layers

Global layers are tokens in `src/styles/tokens.css`. Nothing else may use a z-index above 9.

| Token | Value | Members |
|---|---|---|
| (local) | -1..9 | order inside one component that has its own stacking context: the calendar grid's sticky headings and now-line, a decorative backdrop at -1 |
| `--z-sticky` | 10 | the canvas toolbar, sticky generated-UI blocks |
| `--z-nav` | 30 | the rail and the phone's bottom bar |
| `--z-drawer` | 40 | the background-task notice (`.float-notice`) |
| `--z-modal` | 50 | sheets, dialogs, the command bar and their scrims |
| `--z-menu` | 60 | menus, suggestion lists, the skip link while focused |

A layer may cover content only when the person can still reach what it covers: a menu closes, a sheet traps and returns focus, a sticky bar can be scrolled
out from under. Never solve an overlap by raising a z-index.

## 4. Intentional overlap and exceptions

There are three ways a deliberate overlap is written down. Each one is checked; none is a blanket switch.

1. **Stylesheet reason.** Every `position: fixed|absolute`, negative margin, clipping fixed height and translate offset carries a comment with `layout:` or
   `layer:` in its rule (or on the line above). `scripts/check-layout.mjs` refuses one without it. Pseudo-element decoration and the visually-hidden pattern are
   exempt.
2. **Runtime layer.** The validator treats as an overlay layer anything fixed or sticky, with a layer role (`dialog`, `menu`, `listbox`, `tooltip`), a popover,
   or `data-layer="<name>"`. Content under a layer is not a defect if it can be scrolled out from under it (the validator scrolls to check).
3. **Registered exception.** `data-layout-allow="<key>"` on an element exempts it from the categories its key lists in `tests/layout/exceptions.mjs`, with a
   written reason. An unknown key is itself a violation (`bad-exception`). Current keys: `skip-link`, `count-badge`, `resize-edge`, `calendar-grid`,
   `virtual-list`; selector exceptions only for markup Lumina does not write (KaTeX, Mermaid).

## 5. The checks

| Check | What it catches | Where | Runs |
|---|---|---|---|
| `scripts/check-layout.mjs` | raw z-index, `vh` heights, layout on a bare modifier class (`.md`, `.sm`, `.ok`…), unexplained fixed/absolute, negative margins, clipping fixed heights, translate offsets, the same in inline styles | static, every stylesheet and component | `npm run build` (CI, deploy), tested by `src/styles/layout.test.ts` |
| `tests/layout/validator.mjs` | page overflow, content escaping its box, clipped text, ellipsis with no full text, ellipsis on a flex box, words split mid-word in cells, buttons, labels and headings, colliding text, covered content, covered or unreachable controls, target size, cramped windows, nested scrolling, layout shift | in the browser, on what was really drawn | by the two runners below |
| `tests/layout-browser.mjs` | the validator on every route and state (`tests/layout/scenarios.mjs`) at 4 widths (CI) or 22 (`--full`: 320 to 2560, breakpoint edges, short windows, 200% zoom, 150% text); calibrated first on `tests/layout/selftest.html` | real server code (`preview_mail.py`, `preview_work.py`), `preview_chat.py`, and the mock with stress content | CI part `layout` (blocking) |
| `tests/visual-browser.mjs` | any visible change against approved baselines (`tests/visual/baseline/<platform>/`) | the mock API with a frozen clock | CI part `layout` (blocking), locally |
| older focused checks | chat, mail, calendar, task experience | `browser-layout.js`, `mail-browser.mjs`, `calendar-browser.mjs`, `work-browser.mjs` | locally, see AGENTS.md |

Each violation names the route, viewport, selector, category, both boxes, the computed styles that matter and a suspected cause, with a screenshot that outlines
the boxes (red: the element, yellow: the other one, cyan: where they meet).

### Running them locally

```sh
cd openclaw-project/lumina
npm run build                                           # includes the static layout check
PREVIEW_RATE_LIMITS=0 ../platform/.venv/bin/python tests/preview_mail.py &   # https://127.0.0.1:5183, the whole app on the real server code
../platform/.venv/bin/python tests/preview_work.py &    # http://127.0.0.1:5181, every task state
python3 tests/preview_chat.py &                         # http://127.0.0.1:5178, long and wide conversations
node tests/layout-browser.mjs                           # the CI set; --full for every width; --only <regex>; --viewport 390x844
node tests/visual-browser.mjs                           # starts its own mock API; --only <regex>
```

Reports go to `/tmp/lumina-layout` and `/tmp/lumina-visual` (`LAYOUT_QA_OUTPUT`, `VISUAL_QA_OUTPUT`). `ci/run.sh layout` runs exactly what CI runs. `LAYOUT_JOBS` (default 3) sets how many page states are measured at once. Start the mail fixture with `PREVIEW_RATE_LIMITS=0` for a sweep: a thousand page loads from one address exceed the production request limits (240 reads a minute, 120 anonymous requests a minute), and a refused request makes a page wait or show an error instead of its layout. The switch turns every limit off in that fixture process only; `tests/mail-browser.mjs` needs them on. The sweep keeps its sign-in in `/tmp/lumina-layout-session.json` and waits out a 429 if one comes.

To look into one finding: `node tests/layout/probe.mjs <url> <selector> [w] [h]` prints the boxes and sizing of an element and its ancestors, `tests/layout/rules.mjs` the stylesheet rules that match it, `tests/layout/shot.mjs` a screenshot at any size or text scale.

### Visual baselines

A baseline is approved by a person who looked at it: `node tests/visual-browser.mjs --approve <state>[,<state>]` after reviewing the `*.actual.png`. CI never
approves. A change you meant shows up as a failing state with a `.diff.png`; look at it, then approve that state in the same pull request. Baselines are per
platform because fonts rasterize differently; the CI baselines are `linux`.

## 6. What broke, and the rule it became (2026-11-25 audit)

| Defect | Root cause | Rule |
|---|---|---|
| A finished task's record line drew "3 steps" over its status mark | MasterDetail's root class `.md` (a size container with negative margins) also matched `Status`'s size modifier `md` | no layout on a bare modifier class (`modifier-root`) |
| Phone toolbar took three rows | `flex-basis: calc(100% - 48px)` assumed a 40 px toggle; phone targets are 44 px | no arithmetic on other elements' sizes; `flex-basis` in rem |
| Composer floated 96 px above the bottom at 600-960 px | a `max-width: 960px` rule from the old fixed bottom nav | the frame owns chrome offsets; media queries only in the frame |
| Phone composer took three rows and half the screen | layout chosen by window width; a long chip label | container query on the component; short label form |
| Activity titles cut mid-letter on phones | the 44 px target rule set `display: inline-flex` on an ellipsizing link | truncating text keeps a block box (validator: ellipsis on flex) |
| Sign-in page lost its brand under 960 px | an unscoped `.brand { display: none }` left from the old sidebar | dead and unscoped rules removed |
| New chat with a long draft pushed its text off the top | the composer was centred by a `translateY(calc(…))` | centre by flow (`.thread-col.fresh::after`) |
| Sheets and menus on phones kept 30 px targets | phone rules hung off `.frame.w-compact`; portals render outside `.frame` | the width class is also on `<html>` |
| "Jump to latest" placed at `bottom: 180px` | a guess of the composer's height | anchored to the dock (`bottom: 100%`) |
| File names squeezed to "summ…" in the side panel | buttons kept their row; breakpoint at window 640 px | intrinsic wrapping by the card's own width |
| Answer tables split numbers and words ("1,204,331,/902") | the prose rule `overflow-wrap: anywhere`, inherited into cells, shrank every word's min-content, so the table never overflowed into its scroll box | cells use `break-word`; validator `broken-word` |
