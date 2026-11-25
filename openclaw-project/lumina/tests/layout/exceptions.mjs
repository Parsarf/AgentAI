// The registry of intentional layout exceptions. An element opts out of ONE check by naming a key here in data-layout-allow="<key>" (on itself or an ancestor);
// the validator (tests/layout/validator.mjs) refuses any key that is not listed, so an exception cannot exist without its reason. Keep each one narrow: name the
// categories it covers and nothing more. Selector exceptions are only for markup Lumina does not write (the browser's own, vendored code).
//
// Adding one is a design decision: say in `reason` why the overlap, clip or placement is what the person should see, and where its own check lives instead.
export const EXCEPTIONS = {
  'skip-link': {
    categories: ['unreachable', 'target-size'],
    reason: 'The "Skip to content" link waits above the page until it is focused (frame.css .skip:focus brings it into view). Moving it into the page would put it in the way.',
  },
  'count-badge': {
    categories: ['occluded', 'text-collision'],
    reason: 'A count (waiting tasks) sits on the corner of its rail icon, the way an app badge does. The count is also in the item\'s accessible name; the icon stays recognizable.',
  },
  'resize-edge': {
    categories: ['target-size'],
    reason: 'A zone\'s edge is a thin drag handle by design. WCAG 2.5.8 exempts it because the same change has a full-size control: "Narrower / Wider" in the zone\'s menu, and the arrow keys on the focused edge.',
  },
  'calendar-event': {
    categories: ['target-size'],
    reason: 'A timed event is as tall as it lasts (DESIGN.md, Calendar): its height is essential information, which WCAG 2.5.8 exempts. It is never shorter than one line of its own text, and it opens from the keyboard and the event list too.',
  },
  'calendar-grid': {
    categories: ['nested-scroll'],
    reason: 'The week grid scrolls both ways inside the canvas while the toolbar stays; the canvas itself does not scroll (DESIGN.md, Calendar). Measured by tests/calendar-browser.mjs.',
  },
  'virtual-list': {
    categories: ['nested-scroll'],
    reason: 'A virtualized list (components/frame/List.tsx) owns its own scrolling inside a fill workspace; only the rows in view exist.',
  },
};

// Markup Lumina does not write. Each still names the only categories it is excused from.
export const SELECTOR_EXCEPTIONS = [
  { selector: '.katex', categories: ['text-collision'], reason: 'KaTeX draws a formula by stacking glyphs (fractions, roots) on purpose.' },
  { selector: '.mermaid, [data-mermaid]', categories: ['text-collision', 'escapes-container'], reason: 'Mermaid lays out its own SVG diagram; the box around it scrolls.' },
];
