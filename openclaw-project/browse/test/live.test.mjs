import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, statSync, rmSync, writeFileSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { startSite } from '../fixtures/site.mjs';

process.env.BROWSE_CHROME ||= '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
process.env.BROWSE_ALLOW_LOOPBACK = '1';
process.env.BROWSE_OUT = join(tmpdir(), 'lumina-browse-live-test');
const { Runner } = await import('../runner.mjs');

let site, r, base;
before(async () => { site = await startSite(); base = `http://127.0.0.1:${site.port}`; r = new Runner(); await r.start(); });
after(async () => { await r.stop(); site.close(); });
const sleep = ms => new Promise(res => setTimeout(res, ms));

test('live view: frames are written only while the host marks the stage as watched, and stop when it does not', async () => {
  const out = process.env.BROWSE_OUT; const frame = join(out, 'live.jpg'); const mark = join(out, 'watching');
  rmSync(frame, { force: true }); rmSync(mark, { force: true });
  await r.handle({ cmd: 'open', url: base + '/' });
  await r.liveSync(); await sleep(600);
  assert.equal(existsSync(frame), false, 'no frames while nobody is watching');
  writeFileSync(mark, '1'); await r.liveSync();
  for (let i = 0; i < 40 && !existsSync(frame); i++) await sleep(100);
  assert.ok(existsSync(frame), 'a frame appears once watched'); assert.ok(statSync(frame).size > 500);
  const jpeg = readFileSync(frame); assert.equal(jpeg[0], 0xff); assert.equal(jpeg[1], 0xd8);
  rmSync(mark, { force: true }); await sleep(6500); await r.liveSync();
  assert.equal(r.live, null, 'screencast stops when the marker goes stale');
});

test('takeover input returns at once: a click that starts a slow page load does not hold up the next input', async () => {
  await r.handle({ cmd: 'open', url: base + '/' });
  await r.page.evaluate(() => document.body.insertAdjacentHTML('beforeend', '<a id=s href=/slow style="position:fixed;left:0;top:0;width:200px;height:50px;background:#f00">go</a>'));
  const began = Date.now();
  const res = await r.handle({ cmd: 'xy', action: 'click', x: 50, y: 25 });
  const took = Date.now() - began;
  assert.equal(res.ok, true);
  assert.ok(took < 900, `the click took ${took} ms; it must not wait for the page to settle (the page needs ~1500 ms)`);
  const next = Date.now(); const key = await r.handle({ cmd: 'xy', action: 'key', text: 'Tab' });
  assert.equal(key.ok, true); assert.ok(Date.now() - next < 900, 'the next input is not queued behind a load');
  const title = async () => { try { return await r.page.title(); } catch { return ''; } };   // mid-navigation reads throw
  for (let i = 0; i < 40 && (await title()) !== 'Slow'; i++) await sleep(100);
  assert.equal(await title(), 'Slow', 'the click really happened');
});

test('live view: a capture that is slow to start is not started a second time by the next timer tick', async () => {
  const out = process.env.BROWSE_OUT; const mark = join(out, 'watching');
  await r.handle({ cmd: 'open', url: base + '/' }); await r.liveOff(); rmSync(mark, { force: true });
  let sessions = 0; const real = r.context.newCDPSession.bind(r.context);
  r.context.newCDPSession = async p => { sessions += 1; await sleep(700); return real(p); };       // a busy page answers slowly; the timer ticks every 250 ms
  try {
    writeFileSync(mark, '1');                                                                      // one viewer appears
    await sleep(2500);
    assert.equal(sessions, 1, `one capture session for one viewer (started ${sessions})`);
    assert.ok(r.live, 'and it is running');
  } finally { r.context.newCDPSession = real; rmSync(mark, { force: true }); await r.liveOff(); }
});
