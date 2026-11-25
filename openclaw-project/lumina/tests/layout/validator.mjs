// The layout validator: one function that runs INSIDE the page (Playwright serializes it with page.evaluate), measures what the browser really laid out, and returns
// every violation of the layout contract (docs: lumina/LAYOUT.md). It must stay self-contained: no imports, no closures over module scope.
//
//   const report = await page.evaluate(audit, { exceptions, paint: true, structure: true });
//
// What it looks for (category: what it means):
//   page-overflow       the page scrolls sideways, or something sticks out past the viewport's right edge and is cut by it
//   broken-word         an ordinary word split across two lines in a cell, button, label or heading (a squeezed box)
//   escapes-container   in-flow content spills out of a box that has its own edge (a border or a background) and visible overflow
//   clipped-text        text cut by a box that neither scrolls nor ellipsizes (the reader loses words with no sign that they are missing)
//   truncated-no-full   text intentionally ellipsized, with no way to read the whole of it (no title, accessible name or aria-description nearby)
//   text-collision      two unrelated pieces of text, icons or controls drawn over each other where both can be seen
//   occluded            content covered by an in-flow or plain absolutely positioned box that is not an overlay layer
//   obstructed-control  a control whose centre is covered by something else, even after it is scrolled into view
//   unreachable         a control outside every area that can be scrolled to (placed beyond the start edge or the page)
//   target-size         a control smaller than 24 x 24 px without the spacing WCAG 2.2 allows (warn under 44 px on a phone)
//   nested-scroll       a tall scrolling box inside another tall scrolling box on the same axis (warn)
//   cramped             fixed and sticky bars leave less than 40% of the window's height for content (warn)
//   layout-shift        content moved by itself after it was drawn (cumulative score; needs installShiftObserver)
//   bad-exception       a data-layout-allow value that is not in the registry (an exception must be documented to count)
//
// Intentional overlap is never guessed from z-index numbers. An element is an overlay LAYER when it is fixed or sticky, has a layer role (dialog, menu, listbox,
// tooltip, alertdialog), is a popover, or carries data-layer="<name>". Content covered by a layer is not a defect (a menu over the page, a sticky toolbar over
// scrolled rows) as long as the covered control can be scrolled out from under it. Anything else needs a registered exception: data-layout-allow="<key>" on the
// element or an ancestor, where <key> is in tests/layout/exceptions.mjs with its reason and the categories it covers.
export function audit(opts = {}) {
  const o = Object.assign({ exceptions: {}, selectorExceptions: [], paint: true, structure: true, shifts: true, max: 80, phoneTargets: 44 }, opts);
  const de = document.documentElement;
  const W = de.clientWidth, H = innerHeight;
  const out = [];
  const seen = new Set();
  const cs = new Map();
  const style = el => { let s = cs.get(el); if (!s) { s = getComputedStyle(el); cs.set(el, s); } return s; };
  const r1 = r => ({ x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.right - r.left), h: Math.round(r.bottom - r.top) });

  // A short, stable-ish selector: the nearest ancestor with an id or a component class, then the element's tag and classes.
  const part = el => {
    if (!el || el.nodeType !== 1) return '?';
    const cls = [...el.classList].filter(c => !/^(is-|has-|active|open|selected)$/.test(c)).slice(0, 3).map(c => '.' + CSS.escape(c)).join('');
    const role = el.getAttribute('role');
    return el.tagName.toLowerCase() + (el.id ? '#' + CSS.escape(el.id) : '') + cls + (!cls && role ? `[role="${role}"]` : '') + (!cls && !role && el.getAttribute('aria-label') ? `[aria-label="${el.getAttribute('aria-label').slice(0, 30)}"]` : '');
  };
  const sel = el => {
    const chain = [];
    for (let n = el, i = 0; n && n.nodeType === 1 && n !== document.body && i < 4; n = n.parentElement, i++) {
      chain.unshift(part(n));
      if (n.id || (i > 0 && n.classList.length)) break;
    }
    return chain.join(' > ');
  };
  const component = el => { for (let n = el; n && n !== document.body; n = n.parentElement) { const c = [...(n.classList || [])].find(c => /^(wk|mail|hub|wsp|zone|ws|set|int|gen|files|cal|chat|home|act|live|apps|resp|stress)-/.test(c)); if (c) return c; } return null; };
  const facts = el => { const s = style(el); return { display: s.display, position: s.position, width: s.width, height: s.height, minWidth: s.minWidth, maxWidth: s.maxWidth, maxHeight: s.maxHeight,
    overflow: s.overflowX + ' ' + s.overflowY, whiteSpace: s.whiteSpace, flex: s.flex, zIndex: s.zIndex, margin: s.margin, textOverflow: s.textOverflow, overflowWrap: s.overflowWrap }; };
  const textOf = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80);

  // Registered exceptions: on the element or an ancestor, a key that exists in the registry and covers the category.
  const allowed = (el, category) => {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const v = n.getAttribute('data-layout-allow');
      if (v) for (const key of v.split(/\s+/)) { const e = o.exceptions[key]; if (e && (e.categories || []).includes(category)) return true; }
    }
    for (const x of o.selectorExceptions) if ((x.categories || []).includes(category) && el.closest && el.closest(x.selector)) return true;
    return false;
  };
  const report = (category, severity, el, details) => {
    if (!el || allowed(el, category) || (details.other && allowed(details.other, category))) return;
    const key = category + '|' + sel(el) + '|' + (details.other ? sel(details.other) : '');
    if (seen.has(key) || out.length >= o.max) return;
    seen.add(key);
    if (o.mark) el.setAttribute('data-layout-found', ((el.getAttribute('data-layout-found') || '') + ' ' + category).trim());
    const v = { category, severity, selector: sel(el), component: component(el), text: textOf(el), rect: r1(el.getBoundingClientRect()), styles: facts(el), cause: details.cause || '', note: details.note || '' };
    if (details.other) { v.other = sel(details.other); v.otherRect = r1(details.other.getBoundingClientRect()); v.otherText = textOf(details.other); v.otherStyles = facts(details.other); }
    if (details.rect) v.at = r1(details.rect);
    out.push(v);
  };

  // -- visibility and clipping -------------------------------------------------------------------------------------------------------------------------------
  const visCache = new Map();
  const visible = el => {
    if (visCache.has(el)) return visCache.get(el);
    let ok = true;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const s = style(n);
      if (s.display === 'none' || s.visibility === 'hidden' || s.visibility === 'collapse' || +s.opacity < 0.05 || s.contentVisibility === 'hidden') { ok = false; break; }
      if (s.clip === 'rect(0px, 0px, 0px, 0px)' || /inset\(50%/.test(s.clipPath)) { ok = false; break; }
      if (n.hasAttribute('hidden')) { ok = false; break; }
    }
    if (ok) { const d = el.closest('details:not([open])'); if (d && !(el.closest('summary') && el.closest('summary').parentElement === d) && el !== d) ok = false; }
    if (ok) { const r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1) ok = el.tagName === 'BR'; }
    visCache.set(el, ok);
    return ok;
  };
  const clipsX = s => s.overflowX !== 'visible';
  const clipsY = s => s.overflowY !== 'visible';
  const scrolls = v => v === 'auto' || v === 'scroll';
  const positioned = s => s.position !== 'static' || s.transform !== 'none' || s.filter !== 'none' || s.contain.includes('paint') || s.contain.includes('layout');
  const fixedCB = s => s.transform !== 'none' || s.filter !== 'none' || s.perspective !== 'none' || s.contain.includes('paint') || s.contain.includes('layout') || s.willChange.includes('transform');
  // The rect of `r` (belonging to `el`) after every ancestor that really clips it; also which ancestor clipped it and how (`by`, `scrollable`).
  // `own`: the rect is the element's content (a text run), so the element's own overflow clips it too.
  const clipped = (el, r, own = false) => {
    let box = { left: r.left, top: r.top, right: r.right, bottom: r.bottom };
    let by = null, scrollable = false;
    let pos = own ? null : style(el).position;            // the position of the box whose containing block we are looking for
    for (let n = own ? el : el.parentElement; n && n.nodeType === 1; n = n.parentElement) {
      const s = style(n);
      if (pos === 'fixed' && !fixedCB(s)) continue;        // a fixed box escapes every ancestor that is not its containing block
      if (pos === 'absolute' && !positioned(s)) continue;  // an absolute box escapes the clipping of ancestors that are not positioned
      pos = s.position;
      if (n === document.body || n === de) continue;
      const cx = clipsX(s), cy = clipsY(s);
      if (!cx && !cy) continue;
      const nr = n.getBoundingClientRect();
      const before = { ...box };
      if (cx) { box.left = Math.max(box.left, nr.left + n.clientLeft); box.right = Math.min(box.right, nr.left + n.clientLeft + n.clientWidth); }
      if (cy) { box.top = Math.max(box.top, nr.top + n.clientTop); box.bottom = Math.min(box.bottom, nr.top + n.clientTop + n.clientHeight); }
      if (!by && ((box.right - box.left < before.right - before.left - 1.5) || (box.bottom - box.top < before.bottom - before.top - 1.5))) { by = n; scrollable = (cx && scrolls(s.overflowX)) || (cy && scrolls(s.overflowY)); }
      if (box.right <= box.left || box.bottom <= box.top) return { box: null, by: n, scrollable: scrolls(s.overflowX) || scrolls(s.overflowY) };
    }
    return { box, by, scrollable };
  };
  const insideHScroller = el => { for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) { const s = style(n); if (s.overflowX !== 'visible' && n !== de) return true; } return false; };

  const all = [...document.body.querySelectorAll('*')].filter(el => !['SCRIPT', 'STYLE', 'TEMPLATE', 'NOSCRIPT', 'LINK', 'META'].includes(el.tagName) && !el.closest('svg *'));
  const shown = all.filter(visible);
  const layer = el => {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const s = style(n);
      if (s.position === 'fixed' || s.position === 'sticky') return n;
      if (n.hasAttribute('data-layer') || n.hasAttribute('popover') || /^(dialog|alertdialog|menu|listbox|tooltip)$/.test(n.getAttribute('role') || '') || n.tagName === 'DIALOG') return n;
    }
    return null;
  };
  const INTERACTIVE = 'a[href], button, input:not([type="hidden"]), select, textarea, summary, [role="button"], [role="link"], [role="tab"], [role="switch"], [role="checkbox"], [role="menuitem"], [role="option"], [tabindex]:not([tabindex="-1"])';
  const disabled = el => el.disabled || el.getAttribute('aria-disabled') === 'true' || !!el.closest('[inert]') || !!el.closest('fieldset:disabled');

  for (const el of all) {
    const v = el.getAttribute('data-layout-allow');
    if (v) for (const key of v.split(/\s+/)) if (!o.exceptions[key]) report('bad-exception', 'error', el, { cause: `data-layout-allow="${key}" is not in tests/layout/exceptions.mjs` });
  }

  // -- structure: overflow, escaping, clipping ---------------------------------------------------------------------------------------------------------------
  if (o.structure) {
    const pageWide = de.scrollWidth > de.clientWidth + 1;
    const stick = [];
    for (const el of shown) {
      if (style(el).position === 'fixed' && el.getBoundingClientRect().width >= W) continue;
      const r = el.getBoundingClientRect();
      if (r.right <= W + 1 && r.left >= -1) continue;
      if (insideHScroller(el)) continue;
      const parent = el.parentElement; const pr = parent && parent !== document.body ? parent.getBoundingClientRect() : null;
      if (pr && pr.right > W + 1 && visible(parent) && !insideHScroller(parent)) continue;             // report the outermost element that sticks out
      stick.push(el);
    }
    for (const el of stick.slice(0, 6)) {
      const s = style(el), p = el.parentElement ? style(el.parentElement) : null;
      let cause = 'wider than the viewport';
      if (s.whiteSpace === 'nowrap' || s.whiteSpace === 'pre') cause = `white-space: ${s.whiteSpace} keeps it on one line`;
      else if (p && /flex|grid/.test(p.display) && s.minWidth === 'auto') cause = 'flex/grid item with min-width:auto cannot shrink below its content (needs min-width: 0, or a minmax(0, 1fr) track)';
      else if (/px$/.test(s.width) && s.position !== 'static') cause = 'positioned with a fixed width or offset';
      else if (/\S{40,}/.test(el.textContent || '')) cause = 'a long unbroken string with no overflow-wrap';
      report('page-overflow', 'error', el, { cause, note: pageWide ? `the page is ${de.scrollWidth}px wide in a ${de.clientWidth}px viewport` : 'cut off by the viewport edge (the page itself hides the overflow)' });
    }
    if (pageWide && !stick.length) report('page-overflow', 'error', document.body, { cause: `the page is ${de.scrollWidth}px wide in a ${de.clientWidth}px viewport` });

    for (const el of shown) {
      const s = style(el);
      if (el === document.body || s.display === 'inline' || s.display === 'contents') continue;
      // Escaping: a box with an edge of its own, overflow visible, and in-flow content wider or taller than it.
      const edged = (parseFloat(s.borderLeftWidth) > 0 || parseFloat(s.borderTopWidth) > 0 || (s.backgroundColor !== 'rgba(0, 0, 0, 0)' && s.backgroundColor !== 'transparent') || s.backgroundImage !== 'none');
      if (edged && !['INPUT', 'TEXTAREA', 'SELECT', 'IMG', 'SVG', 'svg', 'IFRAME', 'VIDEO', 'CANVAS'].includes(el.tagName)) {
        const wide = !clipsX(s) && el.scrollWidth > el.clientWidth + 2, tall = !clipsY(s) && el.scrollHeight > el.clientHeight + 2 && el.clientHeight > 0;
        if (wide || tall) {
          const r = el.getBoundingClientRect();
          let culprit = null;
          for (const d of el.querySelectorAll('*')) {
            if (!visible(d)) continue;
            const ds = style(d);
            if (ds.position === 'absolute' || ds.position === 'fixed' || layer(d) !== layer(el)) continue;
            const dr = d.getBoundingClientRect();
            if ((wide && (dr.right > r.right + 1.5 || dr.left < r.left - 1.5)) || (tall && dr.bottom > r.bottom + 1.5)) { culprit = d; break; }
          }
          if (culprit) {
            const cs2 = style(culprit), ps = culprit.parentElement ? style(culprit.parentElement) : null;
            const cause = tall && /px$/.test(s.height) && el.clientHeight < el.scrollHeight ? `the box has a fixed height (${s.height}) but its content needs ${el.scrollHeight}px`
              : cs2.whiteSpace === 'nowrap' ? 'white-space: nowrap on content that can be longer than its box'
              : ps && /flex|grid/.test(ps.display) && cs2.minWidth === 'auto' ? 'flex/grid item with min-width:auto (needs min-width: 0)'
              : /\S{30,}/.test(culprit.textContent || '') ? 'long unbroken text with no overflow-wrap' : 'content larger than the box';
            report('escapes-container', 'error', culprit, { other: el, cause });
          }
        }
      }
    }

    // Text cut by an ancestor that neither scrolls nor ellipsizes; ellipsized text with no way to read it whole.
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode: t => t.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
    const range = document.createRange();
    const truncatedSeen = new Set();
    for (let t; (t = walker.nextNode());) {
      const el = t.parentElement;
      if (!el || !visible(el) || el.closest('svg')) continue;
      range.selectNodeContents(t);
      const r = range.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      const c = clipped(el, r, true);
      if (!c.by || c.scrollable) continue;
      if (!c.box) {
        let full = false;
        for (let n = el, i = 0; n && i < 8 && !full; n = n.parentElement, i++) full = !!(n.getAttribute('title') || n.getAttribute('aria-label'));
        if (!full) report('clipped-text', 'error', el, { other: c.by, cause: 'the whole line is hidden by a box that neither scrolls nor offers the full text (title or accessible name)' });
        continue;
      }
      // Intentional truncation: an ellipsis or a line clamp on the clipping box or between it and the text.
      let intent = null;
      for (let n = el; n && n !== c.by.parentElement; n = n.parentElement) { const s = style(n); if (s.textOverflow === 'ellipsis' || (s.webkitLineClamp && s.webkitLineClamp !== 'none')) { intent = n; break; } }
      if (intent && /flex|grid/.test(style(intent).display) && style(intent).textOverflow === 'ellipsis' && !(style(intent).webkitLineClamp && style(intent).webkitLineClamp !== 'none')) {
        // text-overflow only works on a block container: on a flex or grid box the text is cut mid-letter with no ellipsis.
        report('clipped-text', 'error', el, { other: intent, cause: `text-overflow: ellipsis has no effect on a ${style(intent).display} box, so the text is cut mid-letter (keep a block box for truncating text)`, rect: r });
        continue;
      }
      if (intent) {
        if (truncatedSeen.has(intent)) continue; truncatedSeen.add(intent);
        let full = false;
        for (let n = intent, i = 0; n && i < 6 && !full; n = n.parentElement, i++) full = !!(n.getAttribute('title') || n.getAttribute('aria-label') || n.getAttribute('aria-description') || n.getAttribute('aria-describedby') || n.getAttribute('data-full'));
        if (!full) report('truncated-no-full', 'warn', intent, { cause: 'ellipsized with no title or accessible name holding the whole text' });
        continue;
      }
      const lost = Math.max((r.right - r.left) - (c.box.right - c.box.left), (r.bottom - r.top) - (c.box.bottom - c.box.top));
      if (lost > 2) {
        const bs = style(c.by);
        const cause = /px$/.test(bs.height) && c.by.scrollHeight > c.by.clientHeight + 1 ? `a fixed height (${bs.height}) with overflow: ${bs.overflowY} on content that needs ${c.by.scrollHeight}px`
          : bs.whiteSpace === 'nowrap' || style(el).whiteSpace === 'nowrap' ? 'nowrap text cut without an ellipsis' : `overflow: ${bs.overflowX} ${bs.overflowY} cuts ${Math.round(lost)}px of text`;
        report('clipped-text', 'error', el, { other: c.by, cause, rect: r });
      }
    }

    // Ordinary words split across two lines in short-text boxes (cells, buttons, labels, headings): a box squeezed below its words' width, usually by an inherited
    // `overflow-wrap: anywhere` or `word-break: break-all`. Hyphenated words, paths and URLs may wrap where they break; words longer than 24 characters may too.
    let words = 0;
    for (const box of shown) {
      if (words > 4000) break;
      if (!box.matches('td, th, button, label, summary, h1, h2, h3, h4, h5, [role="tab"], [role="columnheader"], [role="cell"], .chip, .badge')) continue;
      const tw = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
      for (let t; (t = tw.nextNode());) {
        if (!t.parentElement || !visible(t.parentElement)) continue;
        for (const m of t.nodeValue.matchAll(/[^\s\-\/@\u2010-\u2014_.]{2,24}/g)) {
          if (++words > 4000) break;
          if (/[\u3000-\u9fff\uac00-\ud7af]/.test(m[0])) continue;                                        // CJK may break between any two characters
          range.setStart(t, m.index); range.setEnd(t, m.index + m[0].length);
          const rects = [...range.getClientRects()].filter(r => r.width > 0.5);
          if (rects.length > 1 && Math.abs(rects[rects.length - 1].top - rects[0].top) > 2) {
            const ws = style(t.parentElement);
            report('broken-word', 'error', t.parentElement, { other: box, cause: `"${m[0]}" is split across lines (overflow-wrap: ${ws.overflowWrap}, word-break: ${ws.wordBreak}); the box is narrower than its words`, rect: rects[0] });
            break;
          }
        }
      }
    }

    // Nested vertical scrolling of two tall boxes (warn).
    const vscroll = shown.filter(el => scrolls(style(el).overflowY) && el.scrollHeight > el.clientHeight + 1 && el.clientHeight > H * 0.5);
    for (const el of vscroll) { const outer = vscroll.find(p => p !== el && p.contains(el)); if (outer) report('nested-scroll', 'warn', el, { other: outer, cause: 'two tall scrolling boxes on the same axis' }); }

    // Controls that no scrolling can reach.
    for (const el of shown) {
      if (!el.matches(INTERACTIVE) || disabled(el)) continue;
      const r = el.getBoundingClientRect();
      const docLeft = r.left + scrollX, docTop = r.top + scrollY;
      const held = (() => { for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) { const s = style(n); if (s.overflowX !== 'visible' || s.overflowY !== 'visible') return true; if (s.position === 'fixed') return true; } return false; })();
      if (!held && (docLeft + r.width < 0 || docTop + r.height < 0 || docLeft > de.scrollWidth || docTop > de.scrollHeight)) { report('unreachable', 'error', el, { cause: 'placed outside the page (negative offset or off-canvas without being hidden)' }); continue; }
      for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
        const s = style(n);
        if (!scrolls(s.overflowX) && !scrolls(s.overflowY)) continue;
        const nr = n.getBoundingClientRect();
        const rev = /reverse/.test(s.flexDirection) || s.direction === 'rtl';
        if (!rev && (r.right < nr.left - n.scrollLeft - 1 || r.bottom < nr.top - n.scrollTop - 1)) report('unreachable', 'error', el, { other: n, cause: 'before the start edge of its scrolling box, where scrolling cannot reach' });
        break;
      }
    }
  }

  // -- paint: what is drawn over what, in the current viewport ------------------------------------------------------------------------------------------------
  if (o.paint) {
    const modal = [...document.querySelectorAll('[aria-modal="true"], dialog[open]')].filter(visible).pop() || null;
    const inView = b => b && b.right > 0 && b.bottom > 0 && b.left < W && b.top < H;
    // Items: runs of text (one per line box), icons and pictures, and controls.
    const items = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, { acceptNode: t => t.nodeValue.trim() ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT });
    const range = document.createRange();
    for (let t; (t = walker.nextNode());) {
      const el = t.parentElement;
      if (!el || !visible(el) || el.closest('svg, [aria-hidden="true"] .sr, .sr')) continue;
      range.selectNodeContents(t);
      for (const r of range.getClientRects()) {
        if (r.width < 2 || r.height < 2) continue;
        // Shrink a text run to the ink of its glyphs (roughly): line boxes of adjacent lines touch, letters do not.
        const pad = Math.min(r.height * 0.18, 4);
        const c = clipped(el, { left: r.left, top: r.top + pad, right: r.right, bottom: r.bottom - pad }, true);
        if (c.box && inView(c.box)) items.push({ el, box: c.box, kind: 'text' });
      }
    }
    for (const el of shown) {
      if (!(el.tagName === 'svg' || el.tagName === 'IMG' || el.tagName === 'CANVAS' || el.tagName === 'VIDEO')) continue;
      if (el.parentElement && el.parentElement.closest('svg')) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 4 || r.height < 4) continue;
      const c = clipped(el, r);
      if (c.box && inView(c.box)) items.push({ el, box: c.box, kind: 'icon' });
    }
    const grid = new Map(), CELL = 64;
    items.forEach((it, i) => { for (let gx = Math.floor(it.box.left / CELL); gx <= Math.floor(it.box.right / CELL); gx++) for (let gy = Math.floor(it.box.top / CELL); gy <= Math.floor(it.box.bottom / CELL); gy++) { const k = gx + ',' + gy; if (!grid.has(k)) grid.set(k, []); grid.get(k).push(i); } });
    const pairs = new Set();
    const opaque = el => { const s = style(el); const bg = s.backgroundColor; const m = bg.match(/rgba?\(([^)]+)\)/); if (s.backgroundImage !== 'none') return true; if (!m) return false; const p = m[1].split(/[ ,/]+/).filter(Boolean); return p.length < 4 || +p[3] > 0.85; };
    for (const ids of grid.values()) for (let a = 0; a < ids.length; a++) for (let b = a + 1; b < ids.length; b++) {
      const A = items[ids[a]], B = items[ids[b]];
      if (A.el === B.el || A.el.contains(B.el) || B.el.contains(A.el)) continue;
      const key = ids[a] < ids[b] ? ids[a] + ':' + ids[b] : ids[b] + ':' + ids[a];
      if (pairs.has(key)) continue; pairs.add(key);
      const ix = Math.min(A.box.right, B.box.right) - Math.max(A.box.left, B.box.left), iy = Math.min(A.box.bottom, B.box.bottom) - Math.max(A.box.top, B.box.top);
      if (ix < 2 || iy < 2) continue;
      if (modal && (!modal.contains(A.el) || !modal.contains(B.el))) continue;
      const px = Math.max(A.box.left, B.box.left) + ix / 2, py = Math.max(A.box.top, B.box.top) + iy / 2;
      const stack = document.elementsFromPoint(px, py);
      const at = (X, Y) => { for (let n = X.el; n && n !== document.body; n = n.parentElement) { if (n.contains(Y.el)) return -1; const i = stack.findIndex(e => e === n || n.contains(e)); if (i !== -1) return i; } return -1; };
      const ia = at(A, B), ib = at(B, A);
      // The upper item is the one hit first; anything opaque above the lower one that is not its own ancestor hides it.
      const [up, low, lowIdx] = ia !== -1 && (ib === -1 || ia <= ib) ? [A, B, ib] : [B, A, ia];
      let cover = null;
      const limit = lowIdx === -1 ? stack.length : lowIdx;
      for (let k = 0; k < limit; k++) { const e = stack[k]; if (e.contains(low.el) || e === de || e === document.body) continue; if (opaque(e)) { cover = e; break; } }
      if (cover) {
        const coverLayer = layer(cover);
        if (coverLayer && coverLayer !== layer(low.el)) continue;                              // a menu, a dialog, a sticky bar: intentional, and checked for reachability below
        report('occluded', 'error', low.el, { other: cover, cause: `covered by ${style(cover).position === 'absolute' ? 'an absolutely positioned' : 'an in-flow'} box that is not an overlay layer`, rect: { left: px - ix / 2, top: py - iy / 2, right: px + ix / 2, bottom: py + iy / 2 } });
        continue;
      }
      const sa = style(A.el), sb = style(B.el);
      const cause = sa.position === 'absolute' || sb.position === 'absolute' ? 'one of them is absolutely positioned and does not make room for the other'
        : /px$/.test(style(A.el.parentElement || A.el).height) ? 'a fixed height forces lines over each other' : (parseFloat(sa.marginTop) < 0 || parseFloat(sb.marginTop) < 0 || parseFloat(sa.marginLeft) < 0 || parseFloat(sb.marginLeft) < 0) ? 'a negative margin pulls one over the other'
        : (parseFloat(sa.lineHeight) && parseFloat(sa.lineHeight) < parseFloat(sa.fontSize)) ? 'line-height smaller than the font' : 'they share space without a gap';
      report('text-collision', 'error', up.el, { other: low.el, cause, rect: { left: px - ix / 2, top: py - iy / 2, right: px + ix / 2, bottom: py + iy / 2 } });
    }

    // Text covered by a box with no text of its own: at the middle of each line of text, is anything opaque drawn above it that is not an overlay layer?
    const coveredSeen = new Set();
    for (const it of items) {
      if (it.kind !== 'text' || coveredSeen.has(it.el)) continue;
      if (modal && !modal.contains(it.el)) continue;
      const y = (it.box.top + it.box.bottom) / 2;
      // Three points along the line: its start, middle and end (a box over half a line hides words just the same).
      for (const f of [0.1, 0.5, 0.9]) {
        const x = it.box.left + (it.box.right - it.box.left) * f;
        if (x < 0 || y < 0 || x >= W || y >= H || coveredSeen.has(it.el)) continue;
        const stack = document.elementsFromPoint(x, y);
        const own = stack.findIndex(e => e === it.el || e.contains(it.el));
        if (own <= 0) continue;
        for (let k = 0; k < own; k++) {
          const e = stack[k];
          if (it.el.contains(e) || !opaque(e)) continue;
          const l = layer(e);
          if (l && l !== layer(it.el)) break;                                                 // a menu, a dialog, a sticky bar: intentional
          coveredSeen.add(it.el);
          report('occluded', 'error', it.el, { other: e, cause: `covered by ${style(e).position === 'absolute' ? 'an absolutely positioned' : 'an in-flow'} box that is not an overlay layer`, rect: { left: x - 2, top: it.box.top, right: x + 2, bottom: it.box.bottom } });
          break;
        }
      }
    }

    // Controls: is the control itself what a pointer at its centre would hit? If not, scroll it into view and ask again.
    const saved = [];
    const remember = () => { saved.push([window, scrollX, scrollY]); for (const el of all) if (el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth) saved.push([el, el.scrollLeft, el.scrollTop]); };
    // Put every scroll position back right after each re-check, so every other measurement in this pass sees the same page.
    const restore = () => { for (const [el, left, top] of [...saved].reverse()) { if (el === window) scrollTo({ left, top, behavior: 'instant' }); else { el.scrollLeft = left; el.scrollTop = top; } } };
    let rechecks = 0, remembered = false;
    // Kept on the page between passes (the sweep audits each state at several scroll positions): a control seen clear once can be scrolled to; a control already
    // re-checked keeps its verdict. Without this every control passing under a sticky bar was scrolled to again at every step.
    const memo = window.__layoutMemo || (window.__layoutMemo = { clear: new WeakSet(), verdict: new WeakMap() });
    const hitOk = (el, x, y) => { const hit = document.elementFromPoint(x, y); if (!hit) return [false, null]; if (hit === el || el.contains(hit)) return [true, hit];
      const lab = hit.closest('label'); if (lab && (lab.control === el || lab.contains(el))) return [true, hit]; if (el.id && hit.closest(`label[for="${CSS.escape(el.id)}"]`)) return [true, hit]; return [false, hit]; };
    const targets = [];
    for (const el of shown) {
      if (!el.matches(INTERACTIVE) || disabled(el)) continue;
      if (modal && !modal.contains(el)) continue;
      const r = el.getBoundingClientRect();
      // A link that wraps has one box per line; the middle of their union can be empty space. Aim at its largest line instead.
      const frags = style(el).display === 'inline' ? [...el.getClientRects()] : [];
      const aim = frags.length > 1 ? frags.reduce((a, b) => (b.width * b.height > a.width * a.height ? b : a)) : r;
      const c = clipped(el, aim);
      if (!c.box) continue;
      targets.push([el, r, c.box]);
      if (!inView(c.box)) continue;
      if (style(el).pointerEvents === 'none') continue;
      const x = (Math.max(c.box.left, 0) + Math.min(c.box.right, W)) / 2, y = (Math.max(c.box.top, 0) + Math.min(c.box.bottom, H)) / 2;
      let [ok, hit] = hitOk(el, x, y);
      if (ok) { memo.clear.add(el); continue; }
      const hitLayer = hit && layer(hit);
      if (hitLayer && hitLayer !== layer(el) && memo.clear.has(el)) continue;
      if (hitLayer && hitLayer !== layer(el) && memo.verdict.has(el)) { if (!memo.verdict.get(el)) report('obstructed-control', 'error', el, { other: hit, cause: `stays under ${sel(hitLayer)} even when scrolled into view` }); continue; }
      if (hitLayer && hitLayer !== layer(el) && rechecks >= 200) { report('obstructed-control', 'warn', el, { other: hit, cause: `under ${sel(hitLayer)}; not re-checked (more than 200 controls under layers on this page)` }); continue; }
      if (hitLayer && hitLayer !== layer(el)) {
        if (!remembered) { remember(); remembered = true; }
        rechecks++;
        for (const [block, inline] of [['center', 'nearest'], ['start', 'nearest'], ['end', 'nearest'], ['center', 'center']]) {
          el.scrollIntoView({ block, inline, behavior: 'instant' });
          const f2 = frags.length > 1 ? [...el.getClientRects()].reduce((a, b) => (b.width * b.height > a.width * a.height ? b : a)) : el.getBoundingClientRect(), c2 = clipped(el, f2);
          if (c2.box && inView(c2.box)) [ok, hit] = hitOk(el, (Math.max(c2.box.left, 0) + Math.min(c2.box.right, W)) / 2, (Math.max(c2.box.top, 0) + Math.min(c2.box.bottom, H)) / 2);
          if (ok) break;
        }
        restore();
        memo.verdict.set(el, ok);
        if (ok) { memo.clear.add(el); continue; }
      }
      if (hit) report('obstructed-control', 'error', el, { other: hit, cause: hitLayer && hitLayer !== layer(el) ? `stays under ${sel(hitLayer)} even when scrolled into view` : 'another element is drawn over its centre' });
    }
    if (remembered) restore();

    // Room left to read: down the middle of the window, how much is not under a fixed or sticky bar (warn under 40%).
    // Only bars that stay put while the PAGE scrolls count (fixed, or sticky to the document), and only when the page has more content than the window.
    const pageBar = l => { const p = style(l).position; if (p === 'fixed') return true; if (p !== 'sticky') return false;
      for (let n = l.parentElement; n && n !== document.body; n = n.parentElement) { const s = style(n); if (s.overflowX !== 'visible' || s.overflowY !== 'visible') return false; } return true; };
    if (!modal && de.scrollHeight > H + 4) {
      let free = 0, n = 0; const bars = new Set();
      for (let y = 4; y < H; y += 8) { n++; const hit = document.elementFromPoint(W / 2, y); const l = hit && layer(hit); if (l && pageBar(l)) bars.add(l); else free++; }
      if (n && free / n < 0.4) { const big = [...bars].sort((a, b) => b.getBoundingClientRect().height - a.getBoundingClientRect().height)[0];
        report('cramped', 'warn', big, { cause: `only ${Math.round(100 * free / n)}% of the window's height is left for content; bars: ${[...bars].map(sel).join(', ')}` }); }
    }

    // Target size (WCAG 2.2 2.5.8): 24 px, or room for a 24 px circle that touches no other target. Inline links in a sentence are exempt.
    const phone = W < 600;
    for (const [el, r] of targets) {
      if (el.tagName === 'A' && style(el).display === 'inline' && [...el.parentElement.childNodes].some(n => n.nodeType === 3 && n.nodeValue.trim())) continue;
      if (el.matches('input[type="checkbox"], input[type="radio"]') && el.closest('label')) continue;
      if (style(el).pointerEvents === 'none' || el.getAttribute('tabindex') !== null && !el.matches('a, button, input, select, textarea, [role]')) continue;
      const small = Math.min(r.width, r.height);
      if (small >= 24 && !(phone && small < o.phoneTargets)) continue;
      if (small < 24) {
        const cx = (r.left + r.right) / 2, cy = (r.top + r.bottom) / 2;
        const mine = layer(el);
        const crowded = targets.find(([other, or]) => other !== el && !other.contains(el) && !el.contains(other) && layer(other) === mine && Math.hypot(Math.max(or.left - cx, 0, cx - or.right), Math.max(or.top - cy, 0, cy - or.bottom)) < 12);
        if (crowded) report('target-size', 'error', el, { other: crowded[0], cause: `${Math.round(r.width)}x${Math.round(r.height)}px with another target within 12px of its centre` });
      } else report('target-size', 'warn', el, { cause: `${Math.round(r.width)}x${Math.round(r.height)}px on a phone (Lumina's own rule is ${o.phoneTargets}px under 600px)` });
    }
  }

  // -- layout shift (recorded by installShiftObserver) ---------------------------------------------------------------------------------------------------------
  if (o.shifts && window.__layoutShifts) {
    const list = window.__layoutShifts.filter(s => !s.hadRecentInput && s.time >= (window.__layoutShiftMark || 0));
    const score = list.reduce((a, s) => a + s.value, 0);
    if (score > 0.02) {
      const nodes = list.flatMap(s => s.sources).filter(Boolean);
      const el = nodes.map(n => n.node).find(n => n && n.isConnected) || document.body;
      const v = { category: 'layout-shift', severity: score > 0.1 ? 'error' : 'warn', selector: sel(el), component: component(el), text: textOf(el), rect: r1(el.getBoundingClientRect()), styles: facts(el),
        cause: `cumulative layout shift ${score.toFixed(3)} from ${list.length} shift(s) without input`, note: [...new Set(nodes.map(n => n.selector))].slice(0, 6).join(', ') };
      if (!allowed(el, 'layout-shift')) out.push(v);
    }
  }
  return { url: location.pathname + location.search, viewport: { width: W, height: H, dpr: devicePixelRatio, fontSize: getComputedStyle(de).fontSize }, scroll: { x: scrollX, y: scrollY, height: de.scrollHeight }, violations: out };
}

// Installed with page.addInitScript before the app loads: records every layout shift with the nodes that moved.
export function installShiftObserver() {
  window.__layoutShifts = [];
  const name = n => { if (!n || n.nodeType !== 1) return null; return n.tagName.toLowerCase() + (n.id ? '#' + n.id : '') + [...n.classList].slice(0, 2).map(c => '.' + c).join(''); };
  try {
    new PerformanceObserver(list => { for (const e of list.getEntries()) window.__layoutShifts.push({ value: e.value, hadRecentInput: e.hadRecentInput, time: e.startTime, sources: (e.sources || []).map(s => ({ node: s.node, selector: name(s.node) })) }); })
      .observe({ type: 'layout-shift', buffered: true });
  } catch { /* not supported: no shift data */ }
}
