// Try the extension by hand, no model involved: start the bridge, wait for the extension to connect, then run a short scripted browse of the mock shop in a
// new Chrome tab and save the pictures. The platform's device gateway will do the same job with a real decider on the other end.
//   node dev/drive.mjs [--port 8765] [--token dev] [--out /tmp/lumina-ext]
// In Chrome: chrome://extensions -> Developer mode -> Load unpacked -> this folder (browse/extension). Then, in the extension's service worker console:
//   chrome.storage.local.set({ bridge: 'ws://127.0.0.1:8765/device', token: 'dev', devAllowLoopback: true })      (loopback is for this demo only: the mock shop is on 127.0.0.1)
// and click the extension's toolbar button, then "Turn on".
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { wsServer } from './ws-server.mjs';
import { startSite } from '../../fixtures/site.mjs';

const arg = (name, fallback) => { const i = process.argv.indexOf('--' + name); return i > 0 ? process.argv[i + 1] : fallback; };
const port = +arg('port', 8765), token = arg('token', 'dev'), out = arg('out', join(tmpdir(), 'lumina-ext'));
mkdirSync(out, { recursive: true });

const site = await startSite(), base = `http://127.0.0.1:${site.port}`;
console.log(`mock shop at ${base}; waiting for the extension on ws://127.0.0.1:${port}/device (token "${token}")`);

let nextId = 1, shots = 0;
const waiting = new Map();
const { close } = await wsServer({ port, onConnection: conn => {
  let ready = false;
  conn.onMessage(async text => {
    const m = JSON.parse(text);
    if (!ready) {
      if (m.hello !== 1 || m.token !== token) { console.log('refused a connection with the wrong token'); return conn.close(); }
      ready = true; console.log(`extension ${m.version} connected`);
      try { await script(conn); } catch (e) { console.log('script failed:', e.message); }
      console.log('done; pictures are in', out); return conn.close();
    }
    if (m.event) return console.log('event:', JSON.stringify(m));
    if (m.ping) return;
    const w = waiting.get(m.id); if (w) { waiting.delete(m.id); w(m); }
  });
} });

const call = (conn, msg) => new Promise((resolve, reject) => {
  const id = nextId++; const t = setTimeout(() => { waiting.delete(id); reject(new Error(`${msg.cmd} timed out`)); }, 60000);
  waiting.set(id, r => { clearTimeout(t); resolve(r); });
  conn.send(JSON.stringify({ ...msg, id }));
});
const picture = async (conn, label) => { const v = await call(conn, { cmd: 'view' }); const f = join(out, `shot-${String(++shots).padStart(3, '0')}-${label}.jpg`); writeFileSync(f, Buffer.from(v.data, 'base64')); console.log('  picture', f); };
const show = (label, r) => console.log(label, JSON.stringify({ ...r, data: undefined, snapshot: r.snapshot && r.snapshot.split('\n').length + ' controls', text: undefined, elements: undefined }));
const LINE = /^\[(\d+)\]\s+<[a-z]+(?:\s+type=[a-z]+)?>\s+"(.*)"$/;
const ref = (snap, text) => { const m = snap.split('\n').map(l => l.match(LINE)).find(m => m && m[2].includes(text)); if (!m) throw new Error(`no control "${text}"`); return { ref: +m[1], label: m[2] }; };

async function script(conn) {
  show('open', await call(conn, { cmd: 'open', url: base + '/' }));
  let s = await call(conn, { cmd: 'snapshot' }); show('snapshot', s); await picture(conn, 'shop');
  const add = ref(s.snapshot, 'Add to cart');
  show('click add', await call(conn, { cmd: 'act', action: 'click', ref: add.ref, expect: { label: add.label } }));
  s = await call(conn, { cmd: 'snapshot' });
  show('click checkout', await call(conn, { cmd: 'act', action: 'click', ref: ref(s.snapshot, 'Checkout').ref }));
  s = await call(conn, { cmd: 'snapshot' });
  show('type address', await call(conn, { cmd: 'act', action: 'type', ref: ref(s.snapshot, 'Delivery address').ref, value: '12 Main St' }));
  await picture(conn, 'checkout');
  show('close', await call(conn, { cmd: 'close' }));
}
process.on('SIGINT', () => { close(); site.close(); process.exit(0); });
