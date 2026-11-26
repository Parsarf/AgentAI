// Ad-hoc: screenshot a URL at a size.  node tests/layout/shot.mjs <url> <out.png> [width] [height] [scrollY|end] [fontSize]
import { chromium } from '../../../browse/node_modules/playwright-core/index.mjs';
const [url, file, w = 1280, h = 800, scroll = '0', font] = process.argv.slice(2);
const b = await chromium.launch({ channel: 'chrome' }); const c = await b.newContext({ viewport: { width: +w, height: +h }, ignoreHTTPSErrors: true, reducedMotion: 'reduce' }); const p = await c.newPage();
if (font) { const cdp = await c.newCDPSession(p); await cdp.send('Page.setFontSizes', { fontSizes: { standard: +font, fixed: Math.round(+font * .8125) } }); }
if (process.env.STATE) { const s = JSON.parse(process.env.STATE); await c.addCookies(s.cookies); }
await p.goto(url); await p.waitForTimeout(2500);
await p.evaluate(s => scrollTo(0, s === 'end' ? document.documentElement.scrollHeight : +s), scroll); await p.waitForTimeout(300);
await p.screenshot({ path: file }); await b.close();
