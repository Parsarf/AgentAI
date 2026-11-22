---
name: Lumina Obsidian
description: A near-black, Apple-inspired workspace for a private AI assistant, with one restrained electric-violet accent.
colors:
  surface-base: "#060608"
  surface-sidebar: "#0a0a0d"
  surface: "#0e0f13"
  surface-raised: "#15161b"
  surface-overlay: "#191a20"
  surface-inset: "#07080b"
  text-primary: "#f2f2f5"
  text-secondary: "#a3a5af"
  text-muted: "#868995"
  text-disabled: "#5d606b"
  accent: "#7455ff"
  accent-hover: "#9079ff"
  accent-pressed: "#6140ee"
  accent-text: "#b9abff"
  success: "#34d3a0"
  warning: "#f5b942"
  danger: "#ef6a6a"
typography:
  display: { fontFamily: "-apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Inter Variable', Inter, system-ui, sans-serif", fontSize: "clamp(2rem, 4vw, 2.75rem)", fontWeight: 600, letterSpacing: "-.03em" }
  body: { fontSize: ".875rem", lineHeight: 1.5 }
rounded: { xs: "6px", sm: "10px", md: "14px", lg: "20px", pill: "999px" }
spacing: { 1: "4px", 2: "8px", 3: "12px", 4: "16px", 5: "24px", 6: "32px" }
---

# Lumina design system

Source of truth for how Lumina looks. **Theme colours are generated into `src/styles/theme.css`; every other token is in `src/styles/tokens.css`; shared components are in `src/styles/ui.css`, `src/components/ui/` and the workspace frame in `src/components/frame/` (`src/styles/frame.css`).** Read this file before any UI work; `AGENTS.md` points here. Run `npm run check:design` (it also runs in `npm run build`).

Visual reference: the owner-approved Home dashboard image of 25 Oct 2026. It is direction (mood, proportions, control shapes), not a behaviour or accessibility spec. Anything in it that Lumina does not do (for example "Customize", an editable To-do widget, "Sample data") is deliberately not built.

## Direction
Near-black and charcoal surfaces; off-white text; rounded controls (capsules for text actions, circles for icon actions); calm layouts with clear hierarchy. Neutral by default. Roughly nine tenths of any screen is neutral.

Where this follows Apple's guidance: layered materials with clear separation between background, content and overlays; a system font stack; targets of 44 pt (kept as 44px, `--control-lg`) for standalone icon actions; dark-mode contrast that does not rely on colour alone; reduced motion honoured. Where it is a Lumina decision: the violet accent, the glow on the brand mark and primary action, the pill shapes and the exact radii.

## Token architecture
Components use semantic roles, never raw values.

**Colours are generated, not hand-set.** `scripts/tokens/generate.mjs` makes every theme colour (surfaces, fills, text, borders, accent, status) from three inputs: a base colour (`#060608`), an accent (`#7455ff`) and a contrast value, in OKLCH, and writes `src/styles/theme.css` (committed; `npm run build` fails when it is out of date). Normal contrast reproduces the hand-set values this theme had before (tested to an OKLab distance of zero); contrast 1.7 gives the high-contrast theme, chosen in Settings or followed from the system's "more contrast". `src/styles/theme.test.ts` checks text against every surface (4.5:1, and 7:1 at more contrast). A light theme would be another base with the ladders mirrored. To change a colour, change an input and run the generator; never edit `theme.css`.

| Group | Tokens |
|---|---|
| Surfaces | `--surface-base` the page and the chrome (rail, context column) · `--surface-canvas` the canvas, inspector and assistant panels · `--surface-sidebar` (same value, older name) · `--surface` cards/composer · `--surface-raised` inputs, hovered rows, selected · `--surface-overlay` menus/dialogs/sheets (always opaque) · `--surface-inset` terminals |
| Fills | `--fill-subtle`, `--fill-hover`, `--fill-pressed` (neutral overlays for states) |
| Text | `--text-primary`, `--text-secondary`, `--text-muted`, `--text-disabled` (the first three pass 4.5:1 on every surface) |
| Borders | `--border-subtle`, `--border-default`, `--border-strong` |
| Accent | `--accent`, `-hover`, `-pressed`, `--accent-text`, `--accent-soft`, `--accent-line`, `--on-accent`, `--accent-rgb` (for alpha), `--glow-accent` |
| Status | `--success`, `--warning`, `--danger` (+ `-soft`) |
| Type | `--font`, `--font-mono`, `--text-xs`…`--text-3xl` (rem), `--leading-*`, `--weight-*` |
| Shape/size | `--radius-xs…lg/pill`, `--control-sm/md/lg` (30/38/44), `--icon-sm/md/lg`, `--space-1…6` |
| Depth | `--shadow-card`, `--shadow-overlay` |
| Motion | `--ease`, `--dur-fast/dur/dur-slow` |
| Stacking | `--z-sticky/nav/drawer/modal/menu` |

Legacy short names (`--bg`, `--ink`, `--neon`, `--line`…) are aliases; do not use them in new code. Dark is the only theme, in normal and high contrast (`data-contrast='more'`, or the system preference). `data-compact` (two densities: comfortable and compact, Shift+D) and `data-motion` adjust density and animation.

## Accent, glow, elevation, motion
- **Accent (violet) is for**: the brand mark, the primary action, keyboard focus, and selected/active states (the active nav item gets a small violet dot). Everything else is neutral. One violet thing per region is usually enough.
- **Glow** exists in three places only: the brand mark, the primary button/send action, and the active nav dot. Never on borders, cards or text.
- **Elevation** is surface lightness plus a hairline border; menus and dialogs use `--surface-overlay` with `--shadow-overlay`. No frosted transparency.
- **Motion** is short (120–320 ms) and explains a change (a label sliding in, a switch moving). No decorative loops except the thinking orb and planet, which stop with Reduce motion.

## Components (`ui.css`)
| Component | Use |
|---|---|
| `.btn` (+ `.primary`, `.tertiary`, `.danger`, `.small`, `.large`) | Text actions, capsule. One `.primary` per view region. `.danger` is tinted red and only for destructive actions. |
| `.iconbtn` (+ `.small`, `.ghost`, `.send`) | Standalone icon action, circle, 44px. Always give it an `aria-label`. |
| `.chip` (+ `.small`) | Toggles, menu triggers, suggestions. `aria-pressed`/`aria-expanded` mark selection. |
| `.input` | Text input, textarea, select. Invalid: `aria-invalid="true"`. |
| `components/ui/Menu` | Every dropdown and contextual menu. Opaque, portalled, flips at viewport edges, arrow keys, Escape and focus return. Pass `checkable` for choice lists. |
| `components/ui/Toggle` / `.switch` | Labelled on/off settings (`role="switch"`). |
| `.seg` / `.seg-item` | Segmented control and tabs. |
| `.badge` (+ `.accent .success .warning .danger`) | Status. Neutral unless it reports a state. |
| `.panel`, `.card`, `.empty`, `.notice`, `.bar`, `.skeleton`, `.dialog`, `.scrim`, `.kbd` | Surfaces and feedback. |

States every control provides: default, hover, pressed, `:focus-visible` (2px accent ring, 2px offset), selected, disabled (dimmed, no pointer), loading (`aria-busy`), and invalid/error where it applies.

## Work surfaces (`work.css`, `components/work/`)
One vocabulary for a task wherever it appears (chat strip, the assistant panel, Activity, Home, the live view). Classes are prefixed `wk-` (workspace layout `ws-`).

| Piece | Use |
|---|---|
| `Status` (`.wk-status` + `.wk-mark`) | The task's mark and the server's words. Every tone has its own shape as well as colour: filled check (done), hollow dash in the same green (finished, not confirmed), alert (failed/blocked), hand (needs you or held), clock (waiting), stop square (stopped), violet pulse (working). |
| `TaskStrip` | A task in the chat thread. No surface, no border: it sizes to its content. |
| `Permission` (`.wk-permission`) | A permission prompt for one exact tool call. Allow is the one primary action of its item. |
| `Timeline` (`.wk-timeline`, `.wk-row`, `.wk-together`) | What happened, one row per tool call; calls that ran at the same time are bracketed by a hairline in `--accent-line`. Icons from `Icons.tsx`, never glyphs. |
| `Checklist` (`.wk-checklist`) | The assistant's own steps, always captioned "as reported by the assistant". |
| `.wk-list` / `.wk-item` | Lines of tasks separated by hairlines (Activity). Not cards. |
| `.wk-outcome` | The two facts of an ending, side by side: how the run ended, and whether the result was confirmed. |

The live pulse is the only moving thing besides the orb, and stops with Reduce motion. Violet appears on the pulse, the concurrency bracket and the one primary action of an item; nothing else.

## The workspace frame (`src/components/frame/`)
Every page sits in one frame. **No page writes a grid of its own**: a page renders `<Workspace>` and fills its zones; the frame decides where each is shown.

| Zone | What it holds | Where |
|---|---|---|
| Rail (`Nav.tsx`) | Home, Chat; Inbox, Calendar, Files (a group); Activity with the waiting count; Search, Assistant, Safety, Settings and the account at the bottom. A place whose feature is off has no entry. | 60 px, on `--surface-base` (chrome recedes: no coloured icon backgrounds, labels on hover and for screen readers). A bottom bar of five entries under 600 px (Home, Chat, Inbox, Calendar, More). |
| Context | What belongs to the place: chats, mailboxes, calendars, folders, filters, settings sections. Folds away (Ctrl/Cmd+B), remembered. | Left of the canvas from 600 px, a sheet below. On `--surface-base`. |
| Canvas | The page itself, with its own toolbar (title left, controls right). | Always shown; never under 440 px while a zone is docked. |
| Inspector | Details of what is selected (`inspectorKind="selection"`, closes with Esc) or an always-available panel (`"panel"`, folded by the person). | Docked from 1200 px, a sheet below. |
| Assistant (`Assistant.tsx`) | The one assistant panel, for every page but Chat. | Docked from 1500 px, a sheet below (rail button, Ctrl/Cmd+J). |

Width classes (`layout.ts`): compact < 600, medium 600-1199, expanded 1200-1499, large 1500 and up. When docked zones would push the canvas under its minimum, the assistant, then the inspector, then the context become sheets. Zones resize by dragging their edge, by keyboard (focus the edge: arrows, Home, End) and by "Narrower / Wider" in the zone's menu; widths are remembered per person.

The page scrolls (Chat depends on it); side zones are sticky columns with their own scrolling. A `fill` workspace makes the canvas the height of the window for lists and grids that scroll inside (Inbox, Calendar).

**Primitives**, each with a test: `Workspace`, `MasterDetail` (a list and what is opened from it, inside a canvas: side by side from 820px of canvas, one at a time below, decided by a container query so it is right whatever is docked beside the canvas), `Split` (zone edges), `ui/Sheet` (focus trapped, Esc, focus returned, drawn above the page so it never hides the focused element), `Toolbar`, `List` (virtualized, fixed row height per density: 100,000 rows scroll smoothly), `Table` (sortable, keyboard-openable rows), `EmptyState`, `Inspector`.

**The assistant knows the selection.** A page calls `useSelection({ looking, words, actions })`: ids only (a thread, an event, days, a file, a folder, a task, or the page), the words the panel shows ("Looking at: …"), and one-tap actions that fit it. The server checks every id (`POST /v1/assistant/ask`). After an action marked `draft`, the panel offers "Shorter / Longer / More formal / Simpler" as single steps. No generic suggestions.

**Keyboard first, never keyboard only.** Every shortcut is in `src/lib/shortcuts.ts` (a test fails on two with the same key in one place); tooltips, the command bar (Ctrl/Cmd+K or `/`) and the help sheet (`?`) read from it. A page adds its own commands with `useCommands`; each must also exist as a control on the page.

## Mail (`styles/mail.css`, `components/hub/`)
The Inbox is a mail program's three parts: the side column (mailboxes, accounts, each account's own labels or folders), the conversation list, and the open conversation beside it (`MasterDetail`). Classes are prefixed `mail-`; what the Calendar shares stays in `hub.css`.

- **Nothing stands on the page that is not about the mail in front of the reader.** No notice that is always there. What an account may not do is not drawn disabled: it is not drawn, and where a permission would make it possible that is offered once, where it would be used (`AllowChanges`). What an account needs (its access ended, nothing chosen to read) is said on its own row and, when it stops mail arriving, once above the list with the button that fixes it.
- **A row** is three lines at comfortable density (who and when, the subject, the first words) and two at compact. Unread is a violet dot plus weight, never colour alone. A person's mark is two letters on one of six quiet tints (the calendar's data colours mixed far down), the same tint for the same address; on hover or while selecting it becomes the row's checkbox. Quick actions appear on hover and keyboard focus; every one also has a key (`lib/shortcuts.ts`) and a control in the open conversation.
- **An address is never cut short.** Where a whole address has no room, the shortest name that tells the connected accounts apart is shown (what follows the "@" when that differs), with the address as its title.
- **A message is shown in one of two ways, decided by the server** (`platform/agentai_platform/hub_html.py`). One that sets no background is *plain*: drawn in the theme (its font, its text colour, no surface), with the sender's own text colours kept where they read and moved just far enough where they would not. One that sets a background is *designed* (a newsletter, a receipt): shown as sent, on a light sheet with a hairline edge, whatever the theme. The frame is as tall as its message; a message wider than the frame is scaled to fit.
- **A message's page comes from the server, never from the app.** `MessageBody` frames `/v1/hub/mail/frame`, which carries its own content policy. Markup written into a frame by the app (`srcdoc`) inherits the app's policy, which refuses inline styles and remote pictures: every message was then unstyled black serif text on white (production, 2026-11-21). Do not go back to `srcdoc`.
- **Writing** is one bordered sheet: From (a choice for a new message when several accounts are connected), To with suggestions from the customer's own mail, Cc on demand, Subject, the text, then Send with what state the draft is in. It saves itself; there is no Save button.

## Layout, type and icons
- Page pattern: the canvas toolbar names the page; content uses `.panel`/`.card` surfaces on a 16px gap, `EmptyState` when there is nothing, skeletons (not spinners) while loading.
- Speed targets (decision 9 of the remodel): a local action shows its result in under 100 ms; the next likely item is fetched before it is opened (the next mail thread); long lists are virtualized.
- Type: the platform UI font; body 14px, Today's greeting 30px, titles 16-22px. Sizes are rem so browser text settings and zoom work. Weights 400/500/600 only.
- Icons: stroke 1.6, 18–20px in controls, from `components/Icons.tsx`, in `currentColor`.

## Accessibility and responsive rules
- Contrast 4.5:1 for text, 3:1 for control boundaries and focus rings. Never colour alone: statuses also carry text or an icon.
- All actions reachable by keyboard; menus follow the menu pattern; dialogs trap nothing they cannot release.
- `data-motion='reduced'` and `prefers-reduced-motion` remove animations.
- Layouts work from 360px to wide desktop with 200% zoom; long titles ellipsize, prose wraps, code and tables scroll inside their own box. No page scrolls sideways at any width.
- WCAG 2.2 AA is part of the layout: targets at least 24px everywhere and 44px under 600px (`frame.css`, "Phone"); a focused element is never hidden under a sticky bar or a sheet; every drag (a zone's edge, a file onto a folder, a range of days) has a way without dragging. Calendar events keep the height of their duration (WCAG's "essential" exception).

## Building a new feature
1. Read this file. Use `.panel` for the surface, `.hero` or `.page-title` for the heading, `.btn` for actions.
2. Need a dropdown? `<Menu … trigger={({ open, props }) => <button className="chip" {...props}>…</button>} />`.
3. Need colour? Pick a token. If none fits, add one to `tokens.css` and document it here; do not write hex or `rgb()` in a component or page stylesheet (`npm run check:design` fails).
4. Add a test for any new shared behaviour (see `components/ui/Menu.test.tsx`).

## Known exceptions and limitations
- Chart series colours in `components/genui/Cards.tsx` are data colours, not theme colours.
- The planet backdrop and thinking orbs (vendored `src/vendor/thinking-orbs`) draw their own greys.
- Thinking orbs are the nine animations of the vendored `src/vendor/thinking-orbs`, one per state of the agent (`orbFor` in `src/lib/work.ts` picks it from the server's task state; `breathing` is plain thinking). They use a shared clock and an interruptible 600ms blend, and are a still frame at reduced motion. Preview all states and sizes with `npm run dev` at `/app/tests/orbs.html`.
- Pure-black `rgb(0 0 0 / x)` scrims and shadows are allowed.
- The browser's native `<select>` list (opened from `.input` selects) and date inputs are drawn by the OS and cannot be themed; there is no date picker in the app yet.
- Dark is the only theme (normal and high contrast); there is no light theme yet, and nothing in the generator prevents one.
- Toasts are not part of the app, with one exception: the notice when a task sent to the background finishes or needs a decision (`float-notice`). The rail has its own labels on hover; elsewhere native `title` tooltips are used, with the shortcut from the registry.
