// Real-browser check of the task experience on the real state code. Synthetic account, scripted run (see tests/preview_work.py); no assistant, no network beyond localhost.
//   npm run build
//   ../platform/.venv/bin/python tests/preview_work.py &                                   (push stream on, port 5181)
//   PREVIEW_PUSH=0 PREVIEW_PORT=5182 ../platform/.venv/bin/python tests/preview_work.py &  (polling fallback, port 5182)
//   node tests/work-browser.mjs
// Covers, at a desktop and a phone size and with reduced motion: the lifecycle of a run (queued, starting, working, several tools at once, the reply written a piece at a
// time, the ending and its record), a permission prompt answered in the thread, Stop, the same run when the stream is cut mid-way and when there is no stream at all,
// Activity, a task's record and its workspace. Screenshots go to WORK_QA_OUTPUT (default /tmp/lumina-work).
import { chromium } from '../../browse/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';

const PUSH = process.env.WORK_QA_URL || 'http://127.0.0.1:5181';
const POLL = process.env.WORK_QA_POLL_URL || 'http://127.0.0.1:5182';
const out = process.env.WORK_QA_OUTPUT || '/tmp/lumina-work';
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const results = [];
const step = async (name, fn) => { const t = Date.now(); await fn(); results.push(`ok  ${name}  (${((Date.now() - t) / 1000).toFixed(1)}s)`); };

async function layout(page, label) {
  const state = await page.evaluate(() => ({ check: document.documentElement.dataset.layoutCheck, failures: document.documentElement.dataset.layoutFailures, wide: document.documentElement.scrollWidth > innerWidth + 1 }));
  assert.equal(state.wide, false, `${label}: the page overflows sideways`);
  if (state.check) assert.equal(state.check, 'passed', `${label}: ${state.failures}`);
}
const atEnd = page => page.evaluate(() => document.documentElement.scrollHeight - innerHeight - scrollY < 4);
async function say(page, text) { await page.locator('.composer textarea').fill(text); await page.keyboard.press('Enter'); }
const strip = page => page.locator('.wk-strip').last();
// The chat keeps earlier runs: "it ended" always means the NEWEST task's strip, never an older one that happens to say the same words.
const ended = (page, words, timeout = 40000) => page.waitForFunction(w => { const s = [...document.querySelectorAll('.wk-strip')].pop(); return !!s && s.dataset.phase === 'ended' && s.textContent.includes(w); }, words, { timeout });
const going = (page, words, timeout = 20000) => page.waitForFunction(w => { const s = [...document.querySelectorAll('.wk-strip')].pop(); return !!s && s.dataset.phase !== 'ended' && s.textContent.includes(w); }, words, { timeout });

async function run(base, size, { reduced = false, cutStream = false, name }) {
  const context = await browser.newContext({ viewport: size, reducedMotion: reduced ? 'reduce' : 'no-preference' });
  const page = await context.newPage();
  const errors = []; page.on('pageerror', e => errors.push(String(e)));
  const streams = []; page.on('request', r => { if (r.url().includes('/v1/push')) streams.push(r.url()); });
  await page.goto(`${base}/app/chat/live`);
  await page.locator('.composer textarea').waitFor();

  await step(`${name}: a run from queued to its record`, async () => {
    if (cutStream) await page.route('**/v1/push*', route => route.abort());                 // the stream dies before the run: the page must carry on by asking
    await say(page, 'Find me the cheapest direct flight to Lisbon');
    await page.waitForFunction(() => { const s = [...document.querySelectorAll('.wk-strip')].pop(); return !!s && ['queued', 'starting', 'working'].includes(s.dataset.phase); }, null, { timeout: 8000 });
    assert.ok(await page.getByRole('button', { name: 'Stop task' }).isVisible(), 'Stop is in the composer while it works');
    await going(page, 'Searching the web…');
    assert.equal(await strip(page).locator('.agent-thinking').getAttribute('role'), 'status');
    const together = strip(page).getByRole('list', { name: 'Happening at the same time' });
    await together.waitFor({ timeout: 15000 });
    assert.ok((await together.locator('li').count()) >= 2, 'tools running together are each listed');
    await layout(page, `${name} working`);
    assert.ok(await atEnd(page), 'the thread follows the work to the end of the page');
    await page.screenshot({ path: `${out}/${name}-working.png` });
    if (!cutStream && base === PUSH) {                                                       // the reply is seen while it is written, before it is a saved message
      const draft = page.locator('.chat-draft');
      await draft.waitFor({ timeout: 20000 });
      const first = (await draft.innerText()).length; await page.waitForTimeout(400);
      const later = await draft.count() ? (await draft.innerText()).length : first + 1;
      assert.ok(later >= first, 'the draft only grows');
    }
    await ended(page, 'Done · confirmed');
    assert.equal(await page.locator('.chat-draft').count(), 0, 'a finished task never shows its reply as still being written');
    assert.equal(await page.getByRole('button', { name: 'Stop task' }).count(), 0);
    assert.match(await strip(page).innerText(), /5 steps/);
    assert.match(await strip(page).innerText(), /1 did not work/);                           // a page that failed to load is in the record, not hidden
    await strip(page).getByRole('button', { name: 'Details' }).click();
    await strip(page).getByText('3 at the same time').waitFor();
    assert.ok(await strip(page).getByText('did not work').first().isVisible());
    await layout(page, `${name} ended`);
    await page.screenshot({ path: `${out}/${name}-ended.png` });
    if (cutStream) await page.unroute('**/v1/push*');
  });

  await step(`${name}: a permission prompt answered in the thread`, async () => {
    await say(page, 'Compare the fares and ask permission before you approve anything');
    const prompt = strip(page).getByRole('group', { name: 'Permission to use Create issue' });
    await prompt.waitFor({ timeout: 30000 });
    await going(page, 'Waiting for your permission');
    assert.equal(await strip(page).locator('canvas').count(), 0, 'waiting on a person is not drawn as working');
    await layout(page, `${name} permission`);
    await page.screenshot({ path: `${out}/${name}-permission.png` });
    const sends = []; page.on('request', r => { if (r.method() === 'POST' && r.url().endsWith('/send')) sends.push(r.url()); });
    await prompt.getByRole('button', { name: 'Allow' }).click();
    await page.getByText('You allowed create issue on Linear.').last().waitFor({ timeout: 10000 });
    assert.equal(await page.locator('.bubble', { hasText: 'You allowed create issue' }).count(), 0, 'a decision is a record line, not a message bubble');
    await ended(page, 'Done · confirmed');
    assert.deepEqual(sends, [], 'nothing was sent in the customer’s name');
  });

  await step(`${name}: Stop`, async () => {
    await say(page, 'Look again, I will stop you');
    await going(page, 'Searching the web…');
    await page.getByRole('button', { name: 'Stop task' }).click();
    await ended(page, 'Stopped at your request. What was already done is kept.', 15000);
    assert.equal(await page.getByRole('button', { name: /Stop/ }).count(), 0);
    assert.equal(await strip(page).locator('canvas').count(), 0);
    await layout(page, `${name} stopped`);
  });

  await step(`${name}: Activity, a record and a workspace`, async () => {
    await page.goto(`${base}/app/tasks`);
    const needs = page.getByRole('region', { name: /Needs you/ });
    await needs.getByText('Book a dentist appointment for next Tuesday').waitFor();
    assert.ok(await needs.getByRole('group', { name: 'Permission to use Create issue' }).isVisible());
    assert.ok(await needs.getByRole('button', { name: 'Resume' }).isVisible());
    await page.getByText(base === PUSH && !cutStream ? 'Up to date as it happens' : /Up to date as it happens|Refreshing every few seconds/).waitFor();
    await layout(page, `${name} activity`);
    await page.screenshot({ path: `${out}/${name}-activity.png`, fullPage: true });
    const done = page.getByRole('region', { name: 'Finished' });
    await done.getByRole('button', { name: /Not confirmed/ }).click();
    await done.getByRole('link', { name: /spiciest chicken wings/ }).click();
    const verdict = page.getByLabel('How it ended');
    await verdict.getByText('The run finished').waitFor();
    assert.ok(await verdict.getByText('Not confirmed').isVisible());                         // two facts, side by side
    await page.getByText('Not reported as finished').waitFor();                              // the assistant never said the last step was done: neither does the record
    await layout(page, `${name} record`);
    await page.screenshot({ path: `${out}/${name}-record.png`, fullPage: true });
    await page.goto(`${base}/app/live`);                                                    // not a destination: it opens the task that is open
    await page.getByText('Lumina needs your help').waitFor({ timeout: 10000 });
    assert.equal(await page.getByLabel('Text to type into the page').getAttribute('type'), 'password');
    await layout(page, `${name} workspace`);
    await page.screenshot({ path: `${out}/${name}-workspace.png`, fullPage: true });
  });

  if (reduced) await step(`${name}: nothing moves with reduced motion`, async () => {
    await page.goto(`${base}/app/chat/live`);
    await say(page, 'Once more');
    await page.getByRole('list', { name: 'Happening at the same time' }).waitFor({ timeout: 25000 });
    const moving = await page.evaluate(() => [...document.querySelectorAll('.wk-pulse, .agent-state, .wk-fold')].map(e => getComputedStyle(e).animationName).filter(n => n !== 'none'));
    assert.deepEqual(moving, []);
    await page.getByRole('button', { name: 'Stop task' }).click();
    await ended(page, 'Stopped at your request. What was already done is kept.', 15000);
  });
  assert.deepEqual(errors, [], `${name}: page errors`);
  if (base === PUSH && !cutStream) assert.ok(streams.length >= 1, 'the page used the push stream');
  if (base === POLL) assert.equal(streams.length, 0, 'no stream is attempted when the server has no gateway');
  await context.close();
}

try {
  await run(PUSH, { width: 1280, height: 800 }, { name: 'desktop-stream' });
  await run(PUSH, { width: 390, height: 844 }, { name: 'phone-stream', reduced: true });
  await run(PUSH, { width: 1280, height: 800 }, { name: 'desktop-stream-cut', cutStream: true });
  await run(POLL, { width: 390, height: 844 }, { name: 'phone-polling' });
  console.log(results.join('\n')); console.log(`\nall passed; screenshots in ${out}`);
} catch (e) { console.log(results.join('\n')); console.error('\nFAILED:', e.message); process.exitCode = 1; } finally { await browser.close(); }
