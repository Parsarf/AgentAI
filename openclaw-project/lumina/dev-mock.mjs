// Local-only mock of the account API for visual checks and UI tests. Never deployed.  node dev-mock.mjs  -> http://127.0.0.1:5199/app/
import http from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
const DIST = new URL('./dist/', import.meta.url).pathname;
const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.jpg': 'image/jpeg', '.woff2': 'font/woff2', '.txt': 'text/plain' };
const now = () => Math.floor(Date.now() / 1000);
let signedIn = process.env.MOCK_ANON !== '1';
const requests = [
  { id: 'r4', message: 'Build a landing page for hamazor.net', state: 'running', cancel_requested: 0, result: null, created_epoch: now() - 260 },
  { id: 'r3', message: 'Analyze competitor pricing for the three main laptop brands', state: 'completed', cancel_requested: 0, result: 'Acme leads on price; Beta on support.', created_epoch: now() - 7300 },
  { id: 'r2', message: 'Summarize this research paper on retrieval augmented generation', state: 'completed', cancel_requested: 0, result: 'Summary…', created_epoch: now() - 90000 },
  { id: 'r1', message: 'Set up daily stock market report', state: 'failed', cancel_requested: 0, result: null, created_epoch: now() - 200000 },
];
const messages = [
  { id: 1, provenance: 'customer', content: 'What is 17 times 3?', created_at: '2026-10-12T20:25:00Z' },
  { id: 2, provenance: 'agent', content: '51', created_at: '2026-10-12T20:25:30Z' },
];
const events = [
  { kind: 'task_started', payload: { summary: 'Dispatched to the isolated runtime.' }, created_at: '2026-10-12T20:26:00Z' },
  { kind: 'progress', payload: { summary: 'Runtime accepted the request.' }, created_at: '2026-10-12T20:26:02Z' },
  { kind: 'progress', payload: { summary: '3 transcript update(s) recorded.' }, created_at: '2026-10-12T20:26:09Z' },
];
const json = (res, status, body) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(body)); };
const body = req => new Promise(r => { let d = ''; req.on('data', c => d += c); req.on('end', () => { try { r(JSON.parse(d || '{}')); } catch { r({}); } }); });

http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x'); const p = url.pathname;
  if (p === '/_m') { res.writeHead(200, { 'Content-Type': 'text/html' }); return res.end('<body style="margin:0;background:#222"><iframe src="/app/" style="width:390px;height:844px;border:0;background:#000"></iframe></body>'); }
  if (p === '/v1/csrf') return json(res, 200, { csrf_token: 'mock', api_version: 'mock' });
  if (p === '/readyz') return json(res, 200, { foundation_ready: true });
  if (p === '/auth/login') { signedIn = true; return json(res, 200, { ok: true }); }
  if (p === '/auth/logout') { signedIn = false; return json(res, 200, { ok: true }); }
  if (p.startsWith('/v1/')) {
    if (!signedIn) return json(res, 401, { error: 'authentication_required' });
    if (p === '/v1/app') return json(res, 200, { api_version: 'mock', user: { email: 'parsa@example.com', role: 'customer' }, assistant: { state: 'ready' },
      features: { chat: true, execution: true, files: false, uploads: false, telegram: false, connectors: false, billing_mode: 'open', requests: true, usage: true }, limits: { max_message_chars: 16000 } });
    if (p === '/v1/requests') return json(res, 200, { requests });
    if (p === '/v1/conversations') return json(res, 200, { conversations: [{ id: 'c1', project_id: 'p1' }] });
    if (p.endsWith('/messages')) return json(res, 200, { messages, tasks: [] });
    if (p.endsWith('/send')) { const b = await body(req); requests.unshift({ id: 'n' + Date.now(), message: b.message, state: 'waiting', cancel_requested: 0, result: null, created_epoch: now() }); return json(res, 202, { request: { admission: 'reserved' } }); }
    if (p.endsWith('/events')) return json(res, 200, { events });
    if (p.endsWith('/cancel')) return json(res, 202, {});
    if (p === '/v1/costs') return json(res, 200, { reported_microusd: 140000, held_microusd: 0, period_remaining_microusd: 24860000, period_limit_microusd: 25000000 });
    if (p === '/v1/account/connections') return json(res, 200, { connections: [] });
    return json(res, 404, { error: 'unavailable' });
  }
  if (p.startsWith('/app')) {
    const rel = normalize(p.replace(/^\/app\/?/, '') || 'index.html');
    let file = join(DIST, rel);
    if (!file.startsWith(DIST)) { res.writeHead(404); return res.end(); }
    try { const data = await readFile(extname(file) ? file : join(DIST, 'index.html')); res.writeHead(200, { 'Content-Type': MIME[extname(file)] || 'text/html' }); return res.end(data); }
    catch { try { const data = await readFile(join(DIST, 'index.html')); res.writeHead(200, { 'Content-Type': 'text/html' }); return res.end(data); } catch { res.writeHead(404); return res.end(); } }
  }
  res.writeHead(404); res.end();
}).listen(5199, '127.0.0.1', () => console.log('mock on http://127.0.0.1:5199/app/'));
