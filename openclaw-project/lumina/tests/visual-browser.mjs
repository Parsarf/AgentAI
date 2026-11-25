// Visual regression: screenshots of the critical pages and states, compared with APPROVED baselines. Structural layout checks (tests/layout-browser.mjs) say
// whether anything overlaps or is cut; this says whether anything changed. Neither is enough alone (LAYOUT.md).
//
//   npm run build
//   node tests/visual-browser.mjs                       compare every state with its baseline; exit 1 on a difference or a missing baseline
//   node tests/visual-browser.mjs --only chat           a subset (regular expression on the state name)
//   node tests/visual-browser.mjs --approve chat-stress-390   after LOOKING at the new screenshots: make them the baselines (names, or --approve-all)
//
// Determinism: the mock API (dev-mock.mjs) runs with a frozen clock (MOCK_NOW) and the browser's clock is frozen to the same moment; timezone, locale, reduced
// motion and the font (the bundled Inter, so macOS and Linux lay text out alike) are fixed; animations and the caret are off. Baselines are kept per platform
// (tests/visual/baseline/<platform>/), because font rasterization differs between systems.
//
// Comparison: a pixel differs when its colour is further than THRESHOLD from the baseline's AND from every pixel around it (so a one-pixel anti-aliasing shift
// is not a change). A state fails when more than max(MIN_PIXELS, MAX_RATIO of its pixels) differ, or its size changed. Never approve a baseline to make this pass: approve it
// because you looked at the new screenshot and the change is the one you meant. Output: VISUAL_QA_OUTPUT (default /tmp/lumina-visual): actual, baseline and diff.
import { chromium } from '../../browse/node_modules/playwright-core/index.mjs';
import { spawn } from 'node:child_process';
import { copyFile, mkdir, readFile, writeFile, access } from 'node:fs/promises';
import { platform } from 'node:os';

const args = process.argv.slice(2);
const value = name => { const i = args.indexOf(name); return i === -1 ? null : args[i + 1]; };
const ONLY = value('--only') ? new RegExp(value('--only')) : null;
const APPROVE = args.includes('--approve-all') ? 'all' : value('--approve');
const OUT = process.env.VISUAL_QA_OUTPUT || '/tmp/lumina-visual';
const BASE_DIR = new URL(`./visual/baseline/${platform()}/`, import.meta.url).pathname;
const THRESHOLD = 0.1, MAX_RATIO = 0.0001, MIN_PIXELS = 25;     // tight on purpose: two runs on one platform are pixel-identical; a changed word is ~500 pixels
const NOW = Date.UTC(2026, 10, 25, 22, 30, 0) / 1000;               // Wednesday 25 November 2026, 14:30 in Los Angeles
const PORT = Number(process.env.VISUAL_PORT || 5291), ANON_PORT = PORT + 1;

const wide = { width: 1280, height: 800 }, phone = { width: 390, height: 844 };
const STATES = [
  { name: 'home-1280', path: '/app/home', size: wide }, { name: 'home-390', path: '/app/home', size: phone },
  { name: 'chat-task-1280', path: '/app/chat/c1', size: wide }, { name: 'chat-task-390', path: '/app/chat/c1', size: phone },
  { name: 'chat-plain-1280', path: '/app/chat/c2', size: wide },
  { name: 'chat-stress-1280', path: '/app/chat/c4', size: wide }, { name: 'chat-stress-390', path: '/app/chat/c4', size: phone },
  { name: 'chat-stress-table-1280', path: '/app/chat/c4', size: wide, scroll: '.answer-table' }, { name: 'chat-stress-table-390', path: '/app/chat/c4', size: phone, scroll: '.answer-table' },
  { name: 'activity-1280', path: '/app/activity', size: wide }, { name: 'activity-390', path: '/app/activity', size: phone },
  { name: 'inbox-1280', path: '/app/inbox', size: wide, ready: '.mail-row-open' }, { name: 'inbox-390', path: '/app/inbox', size: phone, ready: '.mail-row-open' },
  { name: 'inbox-thread-1280', path: '/app/inbox', size: wide, ready: '.mail-row-open', act: async page => { await page.locator('.mail-row-open').first().click(); await page.waitForTimeout(600); } },
  { name: 'calendar-1280', path: '/app/calendar', size: wide, ready: '.hub-event' }, { name: 'calendar-390', path: '/app/calendar', size: phone, ready: '.cal-new' },
  { name: 'files-1280', path: '/app/files', size: wide },
  { name: 'settings-1280', path: '/app/settings/general', size: wide }, { name: 'settings-390', path: '/app/settings/general', size: phone },
  { name: 'command-bar-1280', path: '/app/home', size: wide, act: async page => { await page.keyboard.press('ControlOrMeta+k'); await page.waitForTimeout(300); } },
  { name: 'login-1280', path: '/app/', size: wide, anon: true, ready: 'input' }, { name: 'login-390', path: '/app/', size: phone, anon: true, ready: 'input' },
].filter(s => !ONLY || ONLY.test(s.name));

// The mock API with a frozen clock (and a second one that is signed out, for the sign-in page).
const servers = [];
async function serve(port, extra = {}) {
  const child = spawn(process.execPath, [new URL('../dev-mock.mjs', import.meta.url).pathname], { env: { ...process.env, MOCK_NOW: String(NOW), MOCK_PORT: String(port), MOCK_THREADS: '400', ...extra }, stdio: ['ignore', 'pipe', 'inherit'] });
  servers.push(child);
  await new Promise((ok, fail) => { child.stdout.on('data', d => { if (String(d).includes('mock on')) ok(); }); child.on('exit', code => fail(new Error('the mock API stopped: ' + code))); setTimeout(() => fail(new Error('the mock API did not start')), 10000); });
}
const stop = () => { for (const s of servers) s.kill(); };
process.on('exit', stop);

await mkdir(OUT, { recursive: true });
await serve(PORT); if (STATES.some(s => s.anon)) await serve(ANON_PORT, { MOCK_ANON: '1' });
const browser = await chromium.launch({ channel: process.env.LAYOUT_CHROME ? undefined : 'chrome', executablePath: process.env.LAYOUT_CHROME || undefined, headless: true });

async function shoot(state) {
  const context = await browser.newContext({ viewport: state.size, deviceScaleFactor: 1, timezoneId: 'America/Los_Angeles', locale: 'en-US', reducedMotion: 'reduce', colorScheme: 'dark' });
  const page = await context.newPage();
  await page.clock.setFixedTime(NOW * 1000);
  await page.goto(`http://127.0.0.1:${state.anon ? ANON_PORT : PORT}${state.path}`, { waitUntil: 'domcontentloaded' });
  const until = async (fn, arg, timeout = 10000) => { const end = Date.now() + timeout; while (Date.now() < end) { if (await page.evaluate(fn, arg).catch(() => false)) return; await page.waitForTimeout(100); } };
  await until(() => !!document.querySelector('#root > *') && !document.querySelector('#root > .login p[role="status"]'));
  if (state.ready) await until(s => !!document.querySelector(s), state.ready);
  // One font everywhere (the bundled Inter), so a baseline means the same thing on every machine of a platform.
  await page.evaluate(() => { document.documentElement.style.setProperty('--font', "'Inter Variable', Inter, sans-serif"); return document.fonts.ready; });
  if (state.act) await state.act(page);
  // A fixed scroll position: a chat scrolls itself to the latest message while its turns (content-visibility: auto) take their real heights, so where it stops
  // varies. The top of the page, or a named element at the top of the window, is the same every time. Twice, because the first scroll renders what it passes.
  for (let i = 0; i < 2; i++) { await page.evaluate(sel => { const el = sel && document.querySelector(sel); if (el) el.scrollIntoView({ block: 'center', behavior: 'instant' }); else scrollTo({ top: 0, behavior: 'instant' }); }, state.scroll || null); await page.waitForTimeout(250); }
  await until(() => ![...document.querySelectorAll('.skeleton, [aria-busy="true"]')].some(e => e.getBoundingClientRect().height > 0), null, 6000);
  await page.waitForTimeout(400);
  const png = await page.screenshot({ animations: 'disabled', caret: 'hide' });
  await context.close();
  return png;
}

// Pixel comparison inside the browser (canvas), so no image library is needed.
let comparer = null;
async function compare(actual, baseline) {
  if (!comparer) { comparer = await (await browser.newContext()).newPage(); }
  return comparer.evaluate(async ([a, b, threshold]) => {
    const load = async b64 => { const bmp = await createImageBitmap(await (await fetch('data:image/png;base64,' + b64)).blob()); const c = new OffscreenCanvas(bmp.width, bmp.height); const x = c.getContext('2d'); x.drawImage(bmp, 0, 0); return { w: bmp.width, h: bmp.height, d: x.getImageData(0, 0, bmp.width, bmp.height).data }; };
    const A = await load(a), B = await load(b);
    if (A.w !== B.w || A.h !== B.h) return { sizeChanged: `${B.w}x${B.h} -> ${A.w}x${A.h}`, ratio: 1, diff: null };
    const max = 35215 * threshold * threshold;                                                  // the YIQ distance pixelmatch uses
    const delta = (i, j, X = A, Y = B) => { const dr = X.d[i] - Y.d[j], dg = X.d[i + 1] - Y.d[j + 1], db = X.d[i + 2] - Y.d[j + 2];
      const y = dr * 0.29889531 + dg * 0.58662247 + db * 0.11448223, iq = dr * 0.59597799 - dg * 0.2741761 - db * 0.32180189, q = dr * 0.21147017 - dg * 0.52261711 + db * 0.31114694;
      return 0.5053 * y * y + 0.299 * iq * iq + 0.1957 * q * q; };
    const out = new OffscreenCanvas(A.w, A.h), ox = out.getContext('2d'), img = ox.createImageData(A.w, A.h);
    let bad = 0;
    for (let yy = 0; yy < A.h; yy++) for (let xx = 0; xx < A.w; xx++) {
      const i = (yy * A.w + xx) * 4;
      // Both ways: this pixel of the new screenshot has a match near it in the baseline, AND this pixel of the baseline has a match near it in the new one
      // (one way only misses a thin stroke that is in one image and not the other).
      const near = (X, Y) => { if (delta(i, i, X, Y) <= max) return true; for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) { const ny = yy + dy, nx = xx + dx; if (ny < 0 || nx < 0 || ny >= A.h || nx >= A.w) continue; if (delta(i, (ny * A.w + nx) * 4, X, Y) <= max) return true; } return false; };
      const same = near(A, B) && near(B, A);
      const g = (A.d[i] + A.d[i + 1] + A.d[i + 2]) / 12;
      if (same) { img.data[i] = img.data[i + 1] = img.data[i + 2] = g; img.data[i + 3] = 255; }
      else { bad++; img.data[i] = 255; img.data[i + 1] = 0; img.data[i + 2] = 80; img.data[i + 3] = 255; }
    }
    ox.putImageData(img, 0, 0);
    const blob = await out.convertToBlob({ type: 'image/png' });
    const diff = await new Promise(done => { const reader = new FileReader(); reader.onload = () => done(String(reader.result).split(',')[1]); reader.readAsDataURL(blob); });
    return { ratio: bad / (A.w * A.h), pixels: bad, diff };
  }, [actual.toString('base64'), baseline.toString('base64'), THRESHOLD]);
}

// Calibration: the same picture must compare as identical, and the same picture with one word changed must fail. A comparer that has gone blind fails here.
{
  const page = await (await browser.newContext()).newPage();
  const draw = word => page.evaluate(async w => { const c = new OffscreenCanvas(320, 120), x = c.getContext('2d'); x.fillStyle = '#0e0f13'; x.fillRect(0, 0, 320, 120);
    x.fillStyle = '#f2f2f5'; x.font = '14px sans-serif'; x.fillText('Set up daily stock market report', 12, 40); x.fillText(w, 12, 80);
    const b = await c.convertToBlob({ type: 'image/png' }); return new Promise(done => { const r = new FileReader(); r.onload = () => done(String(r.result).split(',')[1]); r.readAsDataURL(b); }); }, word);
  const [a, b] = [Buffer.from(await draw('Done'), 'base64'), Buffer.from(await draw('Failed'), 'base64')];
  const same = await compare(a, a), changed = await compare(a, b);
  if (same.pixels !== 0 || !(changed.pixels > MIN_PIXELS)) { console.error(`The visual comparison is miscalibrated: identical -> ${same.pixels} pixels, one word changed -> ${changed.pixels} pixels (needs > ${MIN_PIXELS})`); await browser.close(); stop(); process.exit(2); }
  console.log(`visual calibration: identical pictures match, a one-word change differs by ${changed.pixels} pixels`);
}

const results = [];
for (const state of STATES) {
  const actual = await shoot(state);
  await writeFile(`${OUT}/${state.name}.actual.png`, actual);
  const file = `${BASE_DIR}${state.name}.png`;
  const exists = await access(file).then(() => true, () => false);
  if (APPROVE === 'all' || (APPROVE && APPROVE.split(',').includes(state.name))) {
    await mkdir(BASE_DIR, { recursive: true }); await copyFile(`${OUT}/${state.name}.actual.png`, file);
    results.push({ name: state.name, status: 'approved' }); continue;
  }
  if (!exists) { results.push({ name: state.name, status: 'no baseline', note: `no approved baseline for ${platform()}: look at ${OUT}/${state.name}.actual.png, then --approve ${state.name}` }); continue; }
  const baseline = await readFile(file);
  const r = await compare(actual, baseline);
  if (r.sizeChanged || r.pixels > Math.max(MIN_PIXELS, MAX_RATIO * state.size.width * state.size.height)) {
    await writeFile(`${OUT}/${state.name}.baseline.png`, baseline);
    if (r.diff) await writeFile(`${OUT}/${state.name}.diff.png`, Buffer.from(r.diff, 'base64'));
    results.push({ name: state.name, status: 'changed', note: r.sizeChanged ? `size ${r.sizeChanged}` : `${r.pixels} pixels (${(r.ratio * 100).toFixed(2)}%) differ; see ${state.name}.diff.png` });
  } else results.push({ name: state.name, status: 'same', note: r.pixels ? `${r.pixels} pixels within tolerance` : '' });
}
await browser.close(); stop();

const failed = results.filter(r => r.status === 'changed' || r.status === 'no baseline');
const lines = results.map(r => `${r.status.padEnd(11)} ${r.name}${r.note ? '  ' + r.note : ''}`);
await writeFile(`${OUT}/report.md`, ['# Visual regression', '', `${results.length} states, ${failed.length} need a look. Baselines: ${BASE_DIR}`, '', ...lines.map(l => '    ' + l)].join('\n') + '\n');
console.log(lines.join('\n'));
if (APPROVE) console.log(`\nApproved baselines are in ${BASE_DIR}. Review every approved PNG before you commit it.`);
console.log(`\n${results.length} states, ${failed.length} need a look. Output: ${OUT}`);
process.exit(failed.length && !APPROVE ? 1 : 0);
