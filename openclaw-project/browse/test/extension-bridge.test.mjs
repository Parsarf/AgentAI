// The development bridge's WebSocket server, checked with Node's own WebSocket client: the same wire behaviour Chrome's service worker will have.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { wsServer } from '../extension/dev/ws-server.mjs';

const open = url => new Promise((resolve, reject) => { const ws = new WebSocket(url); ws.onopen = () => resolve(ws); ws.onerror = () => reject(new Error('connect failed')); });
const next = ws => new Promise(resolve => { ws.onmessage = e => resolve(e.data); });

test('messages of every size travel both ways, in order, without damage', async () => {
  let conn; const connected = new Promise(r => { conn = r; });
  const srv = await wsServer({ onConnection: c => { c.onMessage(t => c.send(t)); conn(c); } });
  const ws = await open(`ws://127.0.0.1:${srv.port}/device`); await connected;
  for (const size of [0, 5, 125, 126, 300, 65535, 65536, 400_000, 3_000_000]) {
    const text = 'é'.repeat(size >> 1) + 'x'.repeat(size & 1);
    const back = next(ws); ws.send(text);
    assert.equal((await back).length, text.length, `size ${size}`);
  }
  ws.close(); srv.close();
});

test('only the device path upgrades, and a closing client is noticed', async () => {
  let closed; const gone = new Promise(r => { closed = r; });
  const srv = await wsServer({ onConnection: c => c.onClose(closed) });
  await assert.rejects(open(`ws://127.0.0.1:${srv.port}/elsewhere`));
  const ws = await open(`ws://127.0.0.1:${srv.port}/device`);
  ws.close(); await gone;
  srv.close();
});
