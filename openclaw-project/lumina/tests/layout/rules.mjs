// Ad-hoc: list the stylesheet rules that match an element (and its parent).  node tests/layout/rules.mjs <url> <selector> [width] [height]
import { chromium } from '../../../browse/node_modules/playwright-core/index.mjs';
const [url, selector, w = 1280, h = 800] = process.argv.slice(2);
const b = await chromium.launch({ channel: 'chrome' }); const p = await (await b.newContext({ viewport: { width: +w, height: +h }, ignoreHTTPSErrors: true })).newPage();
await p.goto(url); await p.waitForTimeout(2500);
console.log((await p.evaluate(s => { const el = document.querySelector(s); const out = [];
  const walk = (rules, media) => { for (const r of rules) { if (r.cssRules && !r.selectorText) { walk(r.cssRules, (r.conditionText || r.media?.mediaText || '') ); continue; }
    if (!r.selectorText) continue; for (const [label, node] of [['el', el], ['parent', el.parentElement]]) { try { if (node.matches(r.selectorText) && (!media || matchMedia(media).matches || CSS.supports?.(media))) out.push(label + '  ' + (media ? '@' + media + ' ' : '') + r.cssText.slice(0, 260)); } catch {} } } };
  for (const sh of document.styleSheets) { try { walk(sh.cssRules, ''); } catch {} } return out; }, selector)).join('\n'));
await b.close();
