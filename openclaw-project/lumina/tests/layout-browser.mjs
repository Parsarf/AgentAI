// The layout sweep: every route and the states that matter, at every width, measured in a real browser by tests/layout/validator.mjs.
// Blocking violations (severity "error") fail the run; each one is reported with its route, viewport, selector, rects, computed styles, a suspected cause and a
// screenshot with the offending boxes outlined. See lumina/LAYOUT.md for the contract it enforces.
//
//   npm run build
//   PREVIEW_RATE_LIMITS=0 ../platform/.venv/bin/python tests/preview_mail.py &   the whole account application, real server code (https://127.0.0.1:5183)
//   ../platform/.venv/bin/python tests/preview_work.py &      the task states on the real state code (http://127.0.0.1:5181)
//   python3 tests/preview_chat.py &                           long, wide and many-turn conversations (http://127.0.0.1:5178)
//   node tests/layout-browser.mjs                             the routine set (CI): four widths
//   node tests/layout-browser.mjs --full                      every width, breakpoint edges, short windows, 200% zoom and 150% text
//   node tests/layout-browser.mjs --only inbox --viewport 390x844
//
// Output (LAYOUT_QA_OUTPUT, default /tmp/lumina-layout): report.json, report.md and one PNG per page state with errors. Exit 1 when any error is found.
// A fixture that is not running is reported as not covered (and fails the run under --require-all, which CI uses), never silently skipped.
import { chromium } from '../../browse/node_modules/playwright-core/index.mjs';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { audit, installShiftObserver } from './layout/validator.mjs';
import { EXCEPTIONS, SELECTOR_EXCEPTIONS } from './layout/exceptions.mjs';
import { scenarios } from './layout/scenarios.mjs';

const args = process.argv.slice(2);
const flag = name => args.includes(name);
const value = name => { const i = args.indexOf(name); return i === -1 ? null : args[i + 1]; };
const FULL = flag('--full'), REQUIRE_ALL = flag('--require-all'), REPORT_ONLY = flag('--report-only');
const ONLY = value('--only') ? new RegExp(value('--only')) : null;
const OUT = process.env.LAYOUT_QA_OUTPUT || '/tmp/lumina-layout';
const FIXTURES = {
  mail: process.env.MAIL_QA_URL || 'https://127.0.0.1:5183',
  work: process.env.WORK_QA_URL || 'http://127.0.0.1:5181',
  chat: process.env.CHAT_QA_URL || 'http://127.0.0.1:5178',
  mock: `http://127.0.0.1:${process.env.MOCK_QA_PORT || 5293}`,
};

const vp = (width, height, extra = {}) => ({ name: extra.name || `${width}x${height}`, width, height, ...extra });
const QUICK = [vp(390, 844), vp(768, 1024), vp(1280, 800), vp(1920, 1080)];
const EVERY = [
  vp(320, 640), vp(375, 667), vp(390, 844), vp(599, 900), vp(600, 900), vp(768, 1024), vp(819, 900), vp(821, 900), vp(1024, 768), vp(1199, 900), vp(1200, 900),
  vp(1280, 800), vp(1440, 900), vp(1499, 900), vp(1500, 900), vp(1920, 1080), vp(2560, 1440),
  vp(1280, 520, { name: 'short-1280x520' }), vp(390, 560, { name: 'short-390x560' }),
  vp(640, 400, { name: 'zoom200-1280x800', scale: 2 }),                              // what a 1280 x 800 window lays out at 200% zoom
  vp(390, 844, { name: 'text150-390x844', fontSize: 24 }), vp(1280, 800, { name: 'text150-1280x800', fontSize: 24 }),   // browser text size 150%
];
const wanted = value('--viewport');
const VIEWPORTS = wanted ? [...QUICK, ...EVERY].filter((v, i, a) => (v.name === wanted || `${v.width}x${v.height}` === wanted) && a.findIndex(x => x.name === v.name) === i) : FULL ? EVERY : QUICK;

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch({ channel: process.env.LAYOUT_CHROME ? undefined : 'chrome', executablePath: process.env.LAYOUT_CHROME || undefined, headless: true });
const findings = [], covered = [], uncovered = [];
const started = Date.now();

async function reachable(base) {
  try { const r = await fetch(base + '/app/', { signal: AbortSignal.timeout(4000) }); return r.status < 500; } catch (e) { return String(e.cause?.code || e.message).includes('CERT') || String(e.cause?.message || '').includes('certificate'); }
}
process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';                                     // the mail fixture's certificate is self-signed (local only)

// The mail fixture needs a signed-in customer; that sign-in is kept and shared by every page of the run (the fixture's sign-in limit is on, as in production).
const sessions = {};
async function contextFor(fx, view, { anon = false, reduced = true } = {}) {
  const base = FIXTURES[fx];
  const options = { viewport: { width: view.width, height: view.height }, deviceScaleFactor: view.scale || 1, ignoreHTTPSErrors: true, timezoneId: 'America/Los_Angeles', locale: 'en-US',
    reducedMotion: reduced ? 'reduce' : 'no-preference' };
  if (fx === 'mail' && !anon) {
    sessions.mail ??= (async () => {
      // A sign-in kept from an earlier run against the same fixture is used again (LAYOUT_SESSION; the fixture's sign-in limit is on, as in production).
      const saved = process.env.LAYOUT_SESSION || '/tmp/lumina-layout-session.json';
      const old = await readFile(saved, 'utf8').then(JSON.parse).catch(() => null);
      if (old) { const c = await browser.newContext({ ...options, storageState: old }); const p = await c.newPage(); await p.goto(base + '/app/', { waitUntil: 'domcontentloaded' });
        const ok = await p.evaluate(() => fetch('/v1/hub', { credentials: 'same-origin' }).then(r => r.json()).then(j => Array.isArray(j.accounts) && j.accounts.length >= 2).catch(() => false)); await c.close(); if (ok) return old; }
      const c = await browser.newContext(options); const p = await c.newPage();
      await p.goto(base + '/app/', { waitUntil: 'domcontentloaded' });
      let status = 0;
      for (let attempt = 0; attempt < 4; attempt++) {                                      // a 429 says when to come back (Retry-After: 60)
        status = await p.evaluate(async () => {
          const csrf = (await (await fetch('/v1/csrf', { credentials: 'same-origin' })).json()).csrf_token;
          return (await fetch('/auth/login', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ email: 'mail-preview@example.invalid', password: 'Mail-Preview-2026!' }) })).status;
        });
        if (status !== 429) break;
        console.log('the fixture asks to wait before signing in again (429); waiting 65 s');
        await p.waitForTimeout(65000);
      }
      if (status !== 200) throw new Error('the mail fixture customer could not sign in: ' + status);
      for (const [provider, code] of [['google', 'good-code'], ['microsoft', 'M.C5_BAY.2.U.fixture']]) await p.evaluate(async ([provider, code]) => {
        const call = async (path, body) => { const csrf = (await (await fetch('/v1/csrf', { credentials: 'same-origin' })).json()).csrf_token;
          const r = await fetch(path, body === undefined ? { credentials: 'same-origin' } : { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify(body) });
          return r.json().catch(() => null); };
        const hub = await call('/v1/hub');
        if (!hub || !Array.isArray(hub.accounts)) throw new Error('the fixture did not list its accounts: ' + JSON.stringify(hub).slice(0, 200));
        if (hub.accounts.find(a => a.provider === provider)) return;
        const link = await call('/v1/hub/link', { provider });
        const state = new URL(new URL(link.authorize_url).searchParams.get('real')).searchParams.get('state');
        const id = (await call('/v1/hub/link/finish', { state, code })).connection_id;
        const resources = (await call(`/v1/integrations/${id}/resources`)).resources;
        await call(`/v1/integrations/${id}/grants`, { grants: resources.filter(r => r.kind === 'mailbox' || r.kind === 'calendar') });
        await call('/v1/hub/refresh', { connection_id: id });
      }, [provider, code]);
      const state = await c.storageState();
      await c.close();
      await writeFile(saved, JSON.stringify(state)).catch(() => {});
      return state;
    })();
    options.storageState = await sessions.mail;
  }
  const context = await browser.newContext(options);
  await context.addInitScript(installShiftObserver);
  return context;
}

const until = async (page, fn, arg, timeout = 10000) => { const end = Date.now() + timeout; for (;;) { if (await page.evaluate(fn, arg).catch(() => false)) return true; if (Date.now() > end) return false; await page.waitForTimeout(150); } };
// Settled: the app has drawn (not "Loading…"), no skeleton or busy region is left, fonts are in, and two frames have passed with nothing changing size.
const styled = page => until(page, () => !!getComputedStyle(document.documentElement).getPropertyValue('--surface-base').trim() && [...document.styleSheets].every(s => { try { return s.cssRules.length > 0; } catch { return true; } }), null, 8000);
async function settle(page, ready) {
  await until(page, () => !!document.querySelector('#root > *') && !document.querySelector('#root > .login p[role="status"]'), null, 15000);
  // Never measure an unstyled page (a stylesheet that failed to load under load): reload once, then refuse.
  if (!(await styled(page))) { await page.reload({ waitUntil: 'domcontentloaded' }); if (!(await styled(page))) throw new Error('the stylesheet did not load'); }
  if (ready) await until(page, s => !!document.querySelector(s), ready, 12000);
  await until(page, () => ![...document.querySelectorAll('.skeleton, [aria-busy="true"]')].some(e => e.getBoundingClientRect().height > 0), null, 8000);
  await page.evaluate(() => document.fonts.ready.then(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))));
  let last = '';
  for (let i = 0; i < 12; i++) { const now = await page.evaluate(() => document.documentElement.scrollHeight + ':' + document.body.innerText.length); if (now === last) break; last = now; await page.waitForTimeout(200); }
}

async function outline(page, violations) {
  await page.evaluate(vs => {
    const host = document.createElement('div'); host.id = '__layout_outline'; host.setAttribute('aria-hidden', 'true');
    Object.assign(host.style, { position: 'fixed', inset: '0', pointerEvents: 'none', zIndex: '2147483647' });
    vs.forEach((v, i) => { for (const [r, colour] of [[v.rect, '#ff3b30'], [v.otherRect, '#ffcc00'], [v.at, '#00e5ff']]) { if (!r) continue;
      const b = document.createElement('div'); Object.assign(b.style, { position: 'fixed', left: r.x + 'px', top: r.y + 'px', width: Math.max(r.w, 2) + 'px', height: Math.max(r.h, 2) + 'px', outline: `2px solid ${colour}`, outlineOffset: '-1px' });
      if (colour === '#ff3b30') { const t = document.createElement('span'); t.textContent = `${i + 1} ${v.category}`; Object.assign(t.style, { position: 'absolute', left: '0', top: '-16px', font: '600 11px/14px monospace', background: colour, color: '#fff', padding: '0 3px', whiteSpace: 'nowrap' }); b.append(t); }
      host.append(b); } });
    document.body.append(host);
  }, violations);
}

const fileName = s => s.replace(/[^a-z0-9.-]+/gi, '_').slice(0, 120);
async function measure(page, sc, view, label) {
  const base = { exceptions: EXCEPTIONS, selectorExceptions: SELECTOR_EXCEPTIONS };
  const steps = [];
  steps.push(await page.evaluate(audit, { ...base, structure: true, paint: true, shifts: true }));
  // Paint checks only see the viewport: walk down a long page in screen-sized steps (at most four more).
  const height = await page.evaluate(() => document.documentElement.scrollHeight - innerHeight);
  if (!sc.noScroll && height > view.height * 0.2) {
    for (let i = 1, y = 0; i <= 4 && y < height; i++) {
      y = Math.min(height, Math.round(i * view.height * 0.85));
      await page.evaluate(top => scrollTo({ top, behavior: 'instant' }), y); await page.waitForTimeout(120);
      steps.push(await page.evaluate(audit, { ...base, structure: false, paint: true, shifts: false }));
    }
    await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }));
  }
  let shot = 0;
  for (const step of steps) {
    const errors = step.violations.filter(v => v.severity === 'error');
    const mine = step.violations.map(v => ({ scenario: sc.name, route: sc.path, fixture: sc.fx, viewport: view.name, state: label, scrollY: step.scroll.y, ...v, screenshot: null }));
    if (errors.length) {
      await page.evaluate(y => scrollTo({ top: y, behavior: 'instant' }), step.scroll.y); await page.waitForTimeout(80);
      await outline(page, errors);
      const file = `${fileName(`${sc.name}-${label}-${view.name}-${shot++}`)}.png`;
      await page.screenshot({ path: `${OUT}/${file}` });
      await page.evaluate(() => document.getElementById('__layout_outline')?.remove());
      for (const f of mine) if (f.severity === 'error') f.screenshot = file;
    }
    findings.push(...mine);
  }
  return steps;
}

// Calibration first: the validator must find every known defect on tests/layout/selftest.html and nothing in its known-good sections. A blind validator fails here.
async function calibrate() {
  const context = await browser.newContext({ viewport: { width: 1280, height: 1400 } }); const page = await context.newPage();
  const problems = [];
  await page.setContent(await readFile(new URL('./layout/selftest.html', import.meta.url), 'utf8'));
  await page.evaluate(audit, { exceptions: EXCEPTIONS, selectorExceptions: SELECTOR_EXCEPTIONS, mark: true });
  for (const c of await page.evaluate(() => [...document.querySelectorAll('section[data-expect]')].map(s => ({ expect: s.dataset.expect, text: s.textContent.trim().slice(0, 40),
    found: [...s.querySelectorAll('[data-layout-found]'), ...(s.hasAttribute('data-layout-found') ? [s] : [])].flatMap(e => e.getAttribute('data-layout-found').split(' ')) })))) {
    if (c.expect === 'none' && c.found.length) problems.push(`false alarm (${c.found.join(', ')}) in a known-good case: "${c.text}"`);
    if (c.expect !== 'none' && !c.found.includes(c.expect)) problems.push(`missed ${c.expect} in "${c.text}" (found: ${c.found.join(', ') || 'nothing'})`);
  }
  await page.setContent('<!doctype html><body style="margin:0"><p>Some text.</p><div style="width: calc(100vw + 200px); height: 10px"></div></body>');
  if (!(await page.evaluate(audit, { exceptions: EXCEPTIONS })).violations.some(v => v.category === 'page-overflow')) problems.push('missed page-overflow on a page 200px wider than the window');
  await context.close();
  return problems;
}
if (!flag('--no-selftest')) {
  const off = await calibrate();
  if (off.length) { console.error('The layout validator is miscalibrated:\n  ' + off.join('\n  ')); await browser.close(); process.exit(2); }
  console.log('validator calibration: every known defect found, no false alarm');
  if (flag('--selftest')) { await browser.close(); process.exit(0); }
}

const list = scenarios().filter(sc => !ONLY || ONLY.test(sc.name));
// The mock API is started here (it needs nothing but the build): frozen clock, a 400-thread mailbox.
let mock = null;
if (list.some(sc => sc.fx === 'mock')) {
  const { spawn } = await import('node:child_process');
  mock = spawn(process.execPath, [new URL('../dev-mock.mjs', import.meta.url).pathname], { env: { ...process.env, MOCK_NOW: String(Date.UTC(2026, 10, 25, 22, 30) / 1000), MOCK_PORT: FIXTURES.mock.split(':').pop(), MOCK_THREADS: '400' }, stdio: ['ignore', 'pipe', 'inherit'] });
  await new Promise(ok => { mock.stdout.on('data', d => { if (String(d).includes('mock on')) ok(); }); setTimeout(ok, 8000); });
  process.on('exit', () => mock.kill());
}
const up = {};
for (const fx of new Set(list.map(s => s.fx))) up[fx] = await reachable(FIXTURES[fx]);
const jobs = [];
for (const sc of list) {
  if (!up[sc.fx]) { uncovered.push({ scenario: sc.name, route: sc.path, why: `fixture "${sc.fx}" is not running at ${FIXTURES[sc.fx]}` }); continue; }
  for (const view of sc.viewports ? VIEWPORTS.filter(v => sc.viewports(v)) : VIEWPORTS) jobs.push([sc, view]);
}
const timings = [];
async function runOne(sc, view) {
  const t0 = Date.now();
    const context = await contextFor(sc.fx, view, { anon: sc.anon, reduced: sc.motion !== true });
    const page = await context.newPage();
    const errors = []; page.on('pageerror', e => errors.push(String(e)));
    page.on('dialog', d => { errors.push(`a native ${d.type()} dialog opened: "${d.message().slice(0, 120)}" (it blocks the page; the app should use its own Sheet)`); d.dismiss().catch(() => {}); });
    try {
      if (view.fontSize) { const cdp = await context.newCDPSession(page); await cdp.send('Page.setFontSizes', { fontSizes: { standard: view.fontSize, fixed: Math.round(view.fontSize * 0.8125) } }); }
      const path = typeof sc.path === 'function' ? await sc.path(FIXTURES[sc.fx]) : sc.path;
      await page.goto(FIXTURES[sc.fx] + path, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await settle(page, sc.ready);
      await page.evaluate(() => { window.__layoutShiftMark = performance.now(); });
      const states = sc.states || [{ name: 'default' }];
      for (const st of states) {
        if (st.act) {
          // A state that cannot be reached is tried once more from a fresh load before it counts as not covered (CI fails on it with --require-all).
          let ok = await st.act(page, view).then(() => true, () => false);
          if (!ok) { await page.goto(FIXTURES[sc.fx] + path, { waitUntil: 'domcontentloaded', timeout: 30000 }); await settle(page, sc.ready);
            ok = await st.act(page, view).then(() => true, e => { uncovered.push({ scenario: sc.name, route: path, viewport: view.name, state: st.name, why: 'could not reach the state: ' + String(e.message || e).split('\n')[0] }); return false; }); }
          if (!ok) continue;
          await settle(page, st.ready);
          // Movement the state's own action caused (typing a long draft grows the composer) is the person's doing, as layout-shift scoring counts it.
          await page.evaluate(() => { window.__layoutShiftMark = performance.now(); });
        }
        await measure(page, { ...sc, path }, view, st.name);
        covered.push({ scenario: sc.name, route: path, viewport: view.name, state: st.name });
        if (st.undo) await st.undo(page, view).catch(() => {});
      }
      if (errors.length) findings.push({ scenario: sc.name, route: path, fixture: sc.fx, viewport: view.name, state: '-', category: 'page-error', severity: 'error', selector: '-', text: errors[0].slice(0, 300), cause: 'the page threw while rendering', rect: null, styles: null });
    } catch (e) {
      uncovered.push({ scenario: sc.name, route: String(sc.path), viewport: view.name, why: String(e.message || e).split('\n')[0] });
    } finally { await context.close(); timings.push([Date.now() - t0, `${sc.name}@${view.name}`]); }
}
// A few page states at a time (LAYOUT_JOBS, default 3): each has its own browser context, so they share nothing but the fixtures.
let next = 0, done = 0;
const JOBS = Math.max(1, Number(process.env.LAYOUT_JOBS || 3));
// A page state that does not finish in 120 s (a hung page) is closed and reported as not covered, so one page can never stall the run.
const LIMIT = Number(process.env.LAYOUT_JOB_TIMEOUT || 120000);
const bounded = async (sc, view) => { let timer;
  await Promise.race([runOne(sc, view), new Promise(done => { timer = setTimeout(() => { uncovered.push({ scenario: sc.name, route: String(sc.path), viewport: view.name, why: `did not finish in ${LIMIT / 1000} s` }); done(); }, LIMIT); })]);
  clearTimeout(timer); };
await Promise.all(Array.from({ length: JOBS }, async () => { while (next < jobs.length) { const [sc, view] = jobs[next++]; await bounded(sc, view); done++;
  if (done % 20 === 0 || done === jobs.length) process.stdout.write(`${done}/${jobs.length} page loads, ${findings.filter(f => f.severity === 'error').length} error findings so far\n`); } }));
await browser.close();

// One line per distinct problem (category + selector + other), with every place it was seen.
const groups = new Map();
for (const f of findings) {
  const key = [f.category, f.selector, f.other || ''].join('|');
  if (!groups.has(key)) groups.set(key, { ...f, seen: [] });
  groups.get(key).seen.push(`${f.scenario}/${f.state}@${f.viewport}`);
}
const distinct = [...groups.values()].sort((a, b) => (a.severity === b.severity ? 0 : a.severity === 'error' ? -1 : 1) || a.category.localeCompare(b.category));
const errors = distinct.filter(d => d.severity === 'error');
const md = [`# Layout sweep`, '', `${covered.length} page states measured (${list.length} scenarios x ${VIEWPORTS.length} viewports) in ${Math.round((Date.now() - started) / 1000)} s.`,
  `${errors.length} distinct blocking problem(s), ${distinct.length - errors.length} warning(s). Not covered: ${uncovered.length}.`, '',
  ...distinct.map((d, i) => `${i + 1}. **${d.severity} ${d.category}** \`${d.selector}\`${d.other ? ` vs \`${d.other}\`` : ''} — ${d.cause}${d.note ? ` (${d.note})` : ''}\n   text: "${d.text || ''}"${d.otherText ? ` / "${d.otherText}"` : ''}\n   rect ${JSON.stringify(d.rect)}${d.otherRect ? ' other ' + JSON.stringify(d.otherRect) : ''}\n   seen ${d.seen.length}x: ${[...new Set(d.seen)].slice(0, 8).join(', ')}${d.seen.length > 8 ? ' …' : ''}${d.screenshot ? `\n   screenshot: ${d.screenshot}` : ''}`),
  '', '## Not covered', ...uncovered.map(u => `- ${u.scenario} ${u.state || ''} ${u.viewport || ''}: ${u.why}`),
  '', '## Slowest page states', ...timings.sort((a, b) => b[0] - a[0]).slice(0, 8).map(([ms, n]) => `- ${(ms / 1000).toFixed(1)} s  ${n}`)];
await writeFile(`${OUT}/report.json`, JSON.stringify({ covered, uncovered, findings, distinct }, null, 1));
await writeFile(`${OUT}/report.md`, md.join('\n') + '\n');
console.log(`\n${covered.length} page states, ${errors.length} distinct errors, ${distinct.length - errors.length} warnings, ${uncovered.length} not covered. Report: ${OUT}/report.md`);
const failed = (errors.length && !REPORT_ONLY) || (REQUIRE_ALL && uncovered.length);
process.exit(failed ? 1 : 0);
