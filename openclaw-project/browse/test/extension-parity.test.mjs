// The extension re-implements the runner's hands on top of the same page helpers and the same address policy. These checks fail when the copies drift.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import * as page from '../extension/src/page.js';
import * as rules from '../extension/src/rules.js';
import { urlAllowed as runnerAllowed, privateIp as runnerPrivate } from '../runner.mjs';

const runnerSource = readFileSync(new URL('../runner.mjs', import.meta.url), 'utf8');
const fnSource = (src, name) => { const m = src.match(new RegExp(`(?:^|\\n)(?:export )?(function ${name}\\([^)]*\\) \\{[\\s\\S]*?\\n\\}\\n)`)); assert.ok(m, `${name} not found`); return m[1]; };

test('the page helpers are the runner\'s own, byte for byte', () => {
  const ext = readFileSync(new URL('../extension/src/page.js', import.meta.url), 'utf8');
  for (const name of ['describe', 'hitAt', 'focusActive', 'fingerprint', 'ready']) assert.equal(fnSource(ext, name), fnSource(runnerSource, name), name);
});

test('every helper the executor sends into a page is self-contained (no module scope)', () => {
  for (const f of Object.values(page)) { const src = String(f); assert.ok(!/\bimport\b|\brequire\b/.test(src)); }
});

test('the address policy gives the runner\'s verdict on every address', () => {
  const urls = ['file:///etc/passwd', 'javascript:alert(1)', 'data:text/html,hi', 'chrome://settings', 'http://localhost/', 'http://127.0.0.1/', 'http://10.1.2.3/', 'http://192.168.1.1/', 'http://169.254.169.254/latest',
    'http://172.20.0.1/', 'http://172.32.0.1/', 'http://[::1]/', 'http://[::ffff:10.0.0.1]/', 'http://[fd00::1]/', 'http://100.64.0.1/', 'http://0.0.0.0/', 'http://user:pw@example.com/', 'http://printer.local/', 'http://nas.internal/',
    'ftp://example.com', 'not a url', 'https://example.com/', 'http://93.184.216.34/', 'https://sub.example.co.uk:8443/a?b=c'];
  for (const u of urls) for (const loop of [false, true]) assert.equal(rules.urlAllowed(u, loop), runnerAllowed(u, loop), `${u} loop=${loop}`);
  for (const ip of ['10.0.0.1', '172.15.0.1', '172.16.0.1', '8.8.8.8', '::1', 'fe80::1', '2001:db8::1']) assert.equal(rules.privateIp(ip), runnerPrivate(ip), ip);
});

test('the limits match the runner', () => {
  for (const [name, value] of [['MAX_ELEMENTS', rules.MAX_ELEMENTS], ['MAX_VALUE', rules.MAX_VALUE], ['MAX_URL', rules.MAX_URL], ['MAX_PAGES', rules.MAX_PAGES]])
    assert.match(runnerSource, new RegExp(`\\b${name} = ${value}\\b`), name);
  assert.match(runnerSource, new RegExp(`const SELECTOR = '${rules.SELECTOR.replace(/[[\]().*+?^$|\\]/g, '\\$&')}'`));
});
