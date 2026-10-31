# Obsidian

The visual specification is [DESIGN.md](../../DESIGN.md); its token frontmatter is
normative. [.impeccable/design.json](../../.impeccable/design.json) extends it with
motion, depth, breakpoints and component previews. Update both when an approved
system change lands. Runtime values live in `tokens.css`; `app.css` supplies base
structure and `obsidian.css`, loaded last in `main.tsx`, supplies neutral treatments.

Use graphite surfaces, warm ivory type and neutral primary actions. Capability
colours are compatibility aliases to secondary text. Subdued semantic colours
belong to labelled status and data. Keep flat surfaces, fine borders and no glows.
Preserve existing API behaviour, routes and the contracts in [AGENTS.md](../../AGENTS.md).

Chat uses a bounded, keyboard-focusable transcript above a separate composer dock.
Messages and 48px thinking rows size to content; code and tables scroll locally.
Mobile retains Home, Chat, Live view, Files and More with safe-area clearance.
Preserve real-state orb mapping and both reduced-motion preferences. The faint
globe keeps its existing lifecycle and stays absent on conversation and live routes.

Verification after UI changes: run `npm test` and `npm run build`. Then run
`python3 tests/preview_chat.py` and inspect the production-bundle fixtures at
`http://127.0.0.1:5178/app/chat/working` (also `completed`, `long`, `multiple`,
`overflow`) at desktop and phone widths with both motion settings. Require
`document.documentElement.dataset.layoutCheck === 'passed'`; inspect
`dataset.layoutFailures` on failure and the rendered page for intrinsic bubble
heights, transcript scrolling, local code/table overflow and composer/navigation
clearance. Fixture API content is synthetic. Passing jsdom tests alone does not
verify real layout. The automated Impeccable detector was unavailable during the
2026-10-20 remodel because its engine checksum sidecar could not be verified;
no detector report is claimed.
