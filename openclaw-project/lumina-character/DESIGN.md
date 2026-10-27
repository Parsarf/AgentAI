---
name: Lumina Parchment
description: The drawing's own warm paper, brown ink and an amber signal taken from the creature's glow, for a private agent workspace.
colors:
  bg: "#f1e8d8"
  bg-2: "#eee3d1"
  card: "#f7f4ed"
  elevated: "#eadecd"
  ink: "#24190e"
  ink-2: "#5c4c38"
  ink-3: "#6f5f4a"
  line: "rgba(62,45,31,.12)"
  line-2: "rgba(62,45,31,.22)"
  accent: "#3e2d1f"
  accent-soft: "rgba(62,45,31,.07)"
  accent-line: "rgba(62,45,31,.30)"
  on-accent: "#f7efe2"
  signal: "#f4a514"
  signal-soft: "#f7d8a5"
  signal-ink: "#8a5a00"
  ok: "#55704f"
  warn: "#98650f"
  bad: "#a3392e"
  info: "#56677a"
  creative: "#7a6483"
typography:
  display:
    fontFamily: "'Inter Variable', Inter, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "36px"
    fontWeight: 450
    lineHeight: 1.25
    letterSpacing: "-.035em"
  headline:
    fontFamily: "'Inter Variable', Inter, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "26px"
    fontWeight: 500
    letterSpacing: "-.025em"
  body:
    fontFamily: "'Inter Variable', Inter, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "14px"
    lineHeight: 1.5
    letterSpacing: "-.01em"
  label:
    fontFamily: "'Inter Variable', Inter, system-ui, -apple-system, 'Segoe UI', sans-serif"
    fontSize: "12px"
rounded:
  r-sm: "8px"
  r: "12px"
  r-lg: "16px"
spacing:
  gap: "16px"
  pad: "24px"
  compact-gap: "10px"
  compact-pad: "14px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.r-sm}"
    padding: "9px 16px"
  button-primary-hover:
    backgroundColor: "{colors.ink}"
  button-secondary:
    backgroundColor: "rgba(62,45,31,.05)"
    textColor: "{colors.ink}"
    rounded: "{rounded.r-sm}"
    padding: "9px 16px"
  composer:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.r-lg}"
    padding: "16px 16px 12px"
  chip:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "7px"
    padding: "8px 12px"
  chip-selected:
    backgroundColor: "{colors.signal-soft}"
    textColor: "{colors.ink}"
  navigation-current:
    backgroundColor: "{colors.elevated}"
    textColor: "{colors.ink}"
    rounded: "7px"
  panel:
    backgroundColor: "{colors.bg-2}"
    rounded: "{rounded.r-lg}"
---

# Design System: Lumina Parchment

## Overview

**Creative North Star: "A page of the sketchbook"**

Lumina lives inside its own drawing. The whole workspace is the warm paper the mascot is drawn on: ivory parchment surfaces, brown ink, one amber signal lifted from the creature's glow. The character stands on the page itself, bottom left of the conversation, with no frame around it; the film's paper is multiplied onto the page so there is no edge. The assistant speaks in a serif; the interface stays in Inter.

The composer is a light card at the bottom right. Navigation sits on the same paper with a fine rule. Actual workspace and task state supply the detail: the character's scene, a quiet status line when nothing is running, and the orb's label while work runs. This world was pinned by the owner's reference image (it replaces the earlier Obsidian dark world, which stays available as `data-theme="obsidian"` on `<html>`).

**Key Characteristics:**
- One paper, one ink: no dark panels, no glass.
- Amber is the only chromatic voice (current page, status dot, selected mode, the sparkle mark).
- A serif for the assistant's words, a sans for controls.
- State-driven scene and orb with reduced-motion support.

## Colors

### Primary

Deep brown (`accent`) fills primary actions and carries links; its text is warm ivory (`on-accent`). The softer accent tokens give selection and focus boundaries.

### Signal

Amber (`signal`) marks the current page, the status dot and the sparkle mark; `signal-soft` fills a selected mode chip; `signal-ink` is the amber dark enough for small text on paper.

### Neutral

`bg`, `bg-2`, `card` and `elevated` run from page paper to raised cards. `ink` carries reading text, `ink-2` secondary copy, `ink-3` hints (all at or above 4.5:1 on `bg`). `line` and `line-2` separate surfaces with brown hairlines.

Muted `ok`, `warn` and `bad` accompany status labels; `info`, `creative` and the chart aliases distinguish data with legends and accessible tables.

**The One Signal Rule.** Amber is used for place and state, never for decoration or as a button fill; primary actions are brown.

## Typography

Inter Variable carries controls, navigation and labels. The assistant's replies, the empty-chat greeting and recent-chat titles are set in a system serif (`--serif`: Charter, Iowan Old Style, Georgia), no web font needed; replies are 17px on a 1.6 line. The frontmatter records the desktop greeting, page heading, body and toolbar label roles. The Home greeting becomes two lines on narrow screens (30px, weight 450, line-height 1.3); its desktop size is intentionally modest. Home composer text uses 17px/1.6 on desktop and 16px on narrow screens. Conversation prose uses 15.5px/1.65. Section headings use 15px/500, capability names 13px/500, and hints 11px/1.6. Keep metadata subordinate without using colour alone to convey state.

**Size steps.** Beside the four documented roles, the code uses nine named steps, now tokens in `tokens.css`: `--fs-2xs` 10, `--fs-xs` 11, `--fs-label` 12, `--fs-sm` 13, `--fs-md` 15, `--fs-input` 16 (inputs never go below it on touch), `--fs-lead` 17, `--fs-lg` 18, `--fs-xl` 20, `--fs-2xl` 30. Reach for a step before writing a literal size.

## Layout

Desktop navigation occupies the left edge (232px; 64px collapsed), separated by a fine vertical rule. The shell gap is 24px; the Home column is bounded at 880px and the conversation column at 860px. The toolbar holds the route label and utility controls. Activity opens progressively from existing controls.

Home places the personal greeting above the roomy composer, four capability text actions in two columns, and recent tasks in a ruled list. Choosing a capability seeds and focuses the existing composer. These are Home patterns, not requirements for every page.

At 1200px the intermediate desktop shell uses a 212px sidebar and 16px gap. At 960px and below, Home, Chat, Live view and Files plus More occupy five bottom-navigation slots; More exposes every destination. The shell reserves bottom-navigation and safe-area clearance. At 480px the capability actions become more compact and their trailing chevrons disappear.

Chat has a bounded, keyboard-focusable transcript with its own vertical scroll. The composer dock takes separate space below it. Message and thinking rows pack at the start and size to content; spare height stays between transcript content and composer. Use `minmax(0, 1fr)` tracks, natural prose wrapping, and local horizontal scrolling for fenced code and wide tables. Stick-to-bottom and Jump to latest follow the transcript scroll area.

**Chat stage.** The mascot film is a picture with its own place, never wallpaper under text. From 1180px it is a centred 16:9 stage left of the conversation column (the column is 440–560px, on the plain surface) and its paper edges dissolve into the surface. Below that, or beside the open activity panel under 1700px, it is a banner above the conversation (22dvh, 140–260px) that shortens the pane so the page never scrolls. On a phone held sideways (under 520px tall) the stage steps aside. A caption pill names the real state in plain words (Asleep, Waking up, Ready, Planning, Working, Waiting its turn, Paused, Reconnecting, Needs your answer, Needs your approval, Stopped); "Needs you" states use the accent fill. The drawing is decorative and hidden from assistive technology; the caption is not. Reduced motion shows a still frame of the current scene.

## Elevation & Depth

**The Tonal Depth Rule.** Use surface tone and fine borders for everyday depth; reserve shadows for overlays.

Panels, composer, activity and generated cards are flat at rest. The existing overlay shadow remains a restrained fallback in the implementation; it is recorded in the sidecar. Avoid new glows. The existing globe is barely visible on eligible non-chat pages (opacity .025), preserving its loading, failure and reduced-motion fallback lifecycle.

Controls transition colour, background and borders briefly (160ms). Preserve the existing state-driven thinking orb (48px): actual task/event mapping, 55% preset speed and continuous 600ms state blends. Completed replies remove the indicator; terminal errors do not loop. Both the explicit motion preference and operating-system reduced-motion preference suppress animation and transitions.

## Shapes

Use softly squared controls (`r-sm`), panels (`r`) and composer (`r-lg`). Navigation and chips use tighter corners (7px); the send control is a compact square (44px, 10px corners). Ruled capability actions and recent-task rows have square edges. Keep these distinctions rather than enclosing every action in a card.

**Radius steps.** `--r-xs` 6, `--r-sm` 8, `--r-md` 10, `--r` 12, `--r-xl` 14, `--r-lg` 16 and `--r-pill` 999. Surface washes for hover and ghost fills are `--wash-soft` (6%), `--wash` (7%) and `--wash-strong` (8%) white; `--backdrop` is the modal dimmer.

## Components

- **Buttons:** primary actions use ivory with dark text, changing to reading ivory on hover. Standard buttons have a minimum height of 44px; small variants use 36px. Secondary buttons use a fine border and translucent neutral fill. Focus uses an ivory outline (2px, 3px offset).
- **Composer and inputs:** the composer uses the card surface, stronger border, and large corners. Focus changes its border to the accent boundary; the textarea has no separate outline. Send is 44px square and fades when disabled. Textareas grow to a bounded height (260px). Retain the visible message label for assistive technology and the existing error hint.
- **Chips:** neutral, compact controls; pressed chips use the elevated surface and reading text. Response modes form an inline segmented group; their selected state remains exposed with `aria-pressed`.
- **Panels and cards:** use secondary or card surfaces, fine borders and no resting shadow. Rail cards have 24px padding. Generated content retains its existing functional structures and overflow handling.
- **Navigation:** secondary text becomes reading text on hover/current state; the current route uses an elevated fill. Mobile More supports focus cycling, Escape and focus restoration.
- **Thinking and activity:** keep the orb and short label left aligned. Stop and Activity belong in the chat header. Details reveals reported commands and output; do not reintroduce a Working card.

## Do's and Don'ts

### Do:
- Do reuse the shared tokens across chat, tasks, history, settings and live tools.
- Do keep ordinary prose wrapping and code or tables scrolling within their own containers.
- Do keep the transcript keyboard-focusable and bounded above the separate composer dock.
- Do preserve real task state, orb lifecycle and both reduced-motion mechanisms.

### Don't:
- Don't restore coloured capability tiles, glows or decorative gradients to the neutral controls.
- Don't stretch messages or thinking rows to fill spare pane height.
- Don't render the decorative globe on active conversation or live routes, or put the fallback beneath a loaded globe.
- Don't invent progress, agent reasoning or production content.
