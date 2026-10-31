import { test } from 'node:test';
import assert from 'node:assert/strict';
import { normalisePairCode, bridgeAllowed, PROD_BRIDGE, LUMINA_ORIGIN } from '../extension/src/config.js';
import { describe } from '../extension/src/popup-model.js';
import { readFileSync } from 'node:fs';

test('pairing codes are cleaned up, and only what the platform can issue is accepted', () => {
  assert.equal(normalisePairCode('abcd-2345'), 'ABCD2345'); assert.equal(normalisePairCode('  ab cd 2345 '), 'ABCD2345');
  for (const bad of ['', null, undefined, 12345678, 'ABCD234', 'ABCD23456', 'ABCD2340', 'ABCD2341', 'ABCDOIL5', '<script>', 'ABCD-23-45-67']) assert.equal(normalisePairCode(bad), '', String(bad));
});

test('the alphabet matches the one the platform issues codes from', () => {
  const py = readFileSync(new URL('../../platform/agentai_platform/browse/devices.py', import.meta.url), 'utf8').match(/ALPHABET = '([A-Z0-9]+)'/)[1];
  for (const ch of py) assert.equal(normalisePairCode(ch.repeat(8)), ch.repeat(8), ch);
  for (const ch of 'ILO01') assert.equal(normalisePairCode(ch.repeat(8)), '', ch);
  assert.equal(py.length, 31);
});

test('connect addresses: production or this computer, nothing else', () => {
  for (const ok of [PROD_BRIDGE, 'ws://127.0.0.1:8765/device', 'ws://localhost/v1/device', 'ws://localhost:1/x']) assert.equal(bridgeAllowed(ok), true, ok);
  for (const bad of ['ws://evil.example/device', 'wss://backend.getlumina.pro.evil.example/v1/device', 'ws://127.0.0.1@evil.example/x', 'ws://127.0.0.1:99999999/x', 'wss://127.0.0.1/x', 'http://127.0.0.1/x', '', null, undefined, 5])
    assert.equal(bridgeAllowed(bad), false, String(bad));
});

test('the manifest names exactly the page origin the code accepts, and the production address is the one the proxy routes', () => {
  const m = JSON.parse(readFileSync(new URL('../extension/manifest.json', import.meta.url), 'utf8'));
  assert.deepEqual(m.externally_connectable.matches, [LUMINA_ORIGIN + '/*']);
  assert.equal(m.action.default_popup, 'popup.html'); assert.equal(m.host_permissions, undefined);
  const caddy = readFileSync(new URL('../../platform/deploy/caddy/Caddyfile.getlumina', import.meta.url), 'utf8');
  assert.ok(caddy.startsWith('# Customer HTTPS edge only.') && caddy.includes(new URL(PROD_BRIDGE.replace('wss', 'https')).host + ' {') && caddy.includes('@device path ' + new URL(PROD_BRIDGE.replace('wss', 'https')).pathname));
});

test('the popup says what is true and offers only what makes sense', () => {
  assert.deepEqual(describe({ enabled: false, paired: false }), { text: 'Not connected to Lumina yet.', button: '', askCode: true, tone: 'off' });
  assert.equal(describe({ enabled: false, paired: true }).button, 'Turn on'); assert.equal(describe({ enabled: false, paired: true }).askCode, false);
  assert.equal(describe({ enabled: true, connected: false, paired: true }).tone, 'wait');
  assert.match(describe({ enabled: true, connected: true, paired: true, pairing: true }).text, /^On\./);
  assert.equal(describe({ enabled: true, connected: false, pairing: true }).text, 'Connecting to Lumina…');
  assert.equal(describe(undefined).askCode, true);
});
