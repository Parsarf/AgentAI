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
