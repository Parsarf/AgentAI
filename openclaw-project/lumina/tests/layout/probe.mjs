// Ad-hoc: print the box and computed styles of an element and its ancestors.  node tests/layout/probe.mjs <url> <selector> [width] [height]
import { chromium } from '../../../browse/node_modules/playwright-core/index.mjs';
const [url, selector, w = 1280, h = 800] = process.argv.slice(2);
const b = await chromium.launch({ channel: 'chrome' }); const p = await (await b.newContext({ viewport: { width: +w, height: +h }, ignoreHTTPSErrors: true })).newPage();
await p.goto(url); await p.waitForTimeout(2500);
console.log(JSON.stringify(await p.evaluate(s => { const out = []; let el = document.querySelector(s); for (let i = 0; el && i < 7; i++, el = el.parentElement) { const c = getComputedStyle(el), r = el.getBoundingClientRect();
  out.push({ el: el.tagName + '.' + [...el.classList].join('.'), x: Math.round(r.x), w: Math.round(r.width), h: Math.round(r.height), display: c.display, gtc: c.gridTemplateColumns, flex: c.flex, minW: c.minWidth, width: c.width, justify: c.justifySelf + '/' + c.alignSelf, ws: c.whiteSpace }); } return out; }, selector), null, 1));
await b.close();
