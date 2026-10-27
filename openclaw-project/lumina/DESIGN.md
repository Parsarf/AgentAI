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

Source of truth for how Lumina looks. **Tokens are in `src/styles/tokens.css`, shared components in `src/styles/ui.css` and `src/components/ui/`.** Read this file before any UI work; `AGENTS.md` points here. Run `npm run check:design` (it also runs in `npm run build`).

Visual reference: the owner-approved Home dashboard image of 25 Oct 2026. It is direction (mood, proportions, control shapes), not a behaviour or accessibility spec. Anything in it that Lumina does not do (for example "Customize", an editable To-do widget, "Sample data") is deliberately not built.

## Direction
Near-black and charcoal surfaces; off-white text; rounded controls (capsules for text actions, circles for icon actions); calm layouts with clear hierarchy. Neutral by default. Roughly nine tenths of any screen is neutral.

Where this follows Apple's guidance: layered materials with clear separation between background, content and overlays; a system font stack; targets of 44 pt (kept as 44px, `--control-lg`) for standalone icon actions; dark-mode contrast that does not rely on colour alone; reduced motion honoured. Where it is a Lumina decision: the violet accent, the glow on the brand mark and primary action, the pill shapes and the exact radii.

## Token architecture
Components use semantic roles, never raw values.

| Group | Tokens |
|---|---|
| Surfaces | `--surface-base` page · `--surface-sidebar` · `--surface` cards/composer · `--surface-raised` inputs, hovered rows, selected · `--surface-overlay` menus/dialogs (always opaque) · `--surface-inset` terminals |
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

Legacy short names (`--bg`, `--ink`, `--neon`, `--line`…) are aliases; do not use them in new code. Dark is the only theme; `data-compact` and `data-motion` still adjust density and animation.

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

## Layout, type and icons
- Shell: sidebar (collapsible with Ctrl+B) · main column with a top bar (page title left, search, notifications, motion right) · optional right rail on Home and Tasks. Below 960px the sidebar becomes a bottom bar.
- Page pattern: top bar, then a `.hero` (greeting/title, secondary line, optional date), then content in `.panel`/`.card` surfaces on a 16px gap.
- Type: the platform UI font; body 14px, hero up to 44px, titles 22px. Sizes are rem so browser text settings and zoom work. Weights 400/500/600 only.
- Icons: stroke 1.6, 18–20px in controls, from `components/Icons.tsx`, in `currentColor`.

## Accessibility and responsive rules
- Contrast 4.5:1 for text, 3:1 for control boundaries and focus rings. Never colour alone: statuses also carry text or an icon.
- All actions reachable by keyboard; menus follow the menu pattern; dialogs trap nothing they cannot release.
- `data-motion='reduced'` and `prefers-reduced-motion` remove animations.
- Layouts work from 360px to wide desktop with 200% zoom; long titles ellipsize, prose wraps, code and tables scroll inside their own box.

## Building a new feature
1. Read this file. Use `.panel` for the surface, `.hero` or `.page-title` for the heading, `.btn` for actions.
2. Need a dropdown? `<Menu … trigger={({ open, props }) => <button className="chip" {...props}>…</button>} />`.
3. Need colour? Pick a token. If none fits, add one to `tokens.css` and document it here; do not write hex or `rgb()` in a component or page stylesheet (`npm run check:design` fails).
4. Add a test for any new shared behaviour (see `components/ui/Menu.test.tsx`).

## Known exceptions and limitations
- Chart series colours in `components/genui/Cards.tsx` are data colours, not theme colours.
- The planet backdrop and thinking orbs (vendored `src/vendor/thinking-orbs`) draw their own greys.
- Pure-black `rgb(0 0 0 / x)` scrims and shadows are allowed.
- The browser's native `<select>` list (opened from `.input` selects) and date inputs are drawn by the OS and cannot be themed; there is no date picker in the app yet.
- Dark is the only theme; there is no light theme.
- Toasts and tooltips are not part of the app; native `title` tooltips are used until a need appears.
