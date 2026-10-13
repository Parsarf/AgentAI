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
const ph = (id, title, deps = [], extra = {}) => ({ id, title, description: 'Describe the work for this phase.', enabled: true, optional: false, requiresApproval: false, dependsOn: deps, ...extra });
const PLAN = { schemaVersion: '1.0', type: 'task_plan', title: 'Online store', summary: 'Plan for a small e-commerce site with sign-in and payments.', phases: [
  ph('analyze', 'Analyze requirements'), ph('design', 'Design architecture', ['analyze']), ph('frontend', 'Build frontend', ['design']), ph('backend', 'Implement backend', ['design']),
  ph('test', 'Test application', ['frontend', 'backend']), ph('deploy', 'Deploy application', ['test'], { optional: true, requiresApproval: true })] };
const messages = [
  { id: 1, provenance: 'customer', content: 'What is 17 times 3?', created_at: '2026-10-12T20:25:00Z' },
  { id: 2, provenance: 'agent', content: '51', created_at: '2026-10-12T20:25:30Z' },
];
const events = [
  { kind: 'task_started', payload: { summary: 'Dispatched to the isolated runtime.' }, created_at: '2026-10-12T20:26:00Z' },
  { kind: 'progress', payload: { summary: 'Runtime accepted the request.' }, created_at: '2026-10-12T20:26:02Z' },
  { kind: 'progress', payload: { summary: '3 transcript update(s) recorded.' }, created_at: '2026-10-12T20:26:09Z' },
];

const card = (id, kind, spec) => ({ id, conversation_id: 'c1', anchor_message_id: 2, kind, schema_version: '1.0', spec: { schemaVersion: '1.0', type: kind, ...spec }, state: {}, version: 1, status: 'final', launched_request_id: null });
const CARDS = [
  card('t1', 'table', { title: 'Cheapest carbon paddles', caption: 'Prices from seller pages, checked today.', highlightRow: 0, columns: [{ id: 'name', label: 'Paddle', type: 'text' }, { id: 'price', label: 'Price', type: 'currency' }, { id: 'rating', label: 'Rating', type: 'rating' }, { id: 'url', label: 'Page', type: 'link' }],
    rows: [{ name: 'Selkirk Vanguard', price: 89.99, rating: 4.6, url: 'https://example.com/a' }, { name: 'JOOLA Ben Johns', price: 129, rating: 4.8, url: 'https://example.com/b' }, { name: 'Paddletek Bantam', price: 99.5, rating: 4.4, url: 'https://example.com/c' }, { name: 'Engage Pursuit', price: 149, rating: 4.7, url: 'https://example.com/d' }, { name: 'CRBN 1', price: 199.95, rating: 4.9, url: 'https://example.com/e' }, { name: 'Gearbox CX14', price: 179, rating: 4.5 }, { name: 'Onix Z5', price: 74.99, rating: 4.1, url: 'https://example.com/g' }] }),
  card('c1', 'chart', { chart: 'bar', title: 'Monthly spend', unit: '$', labels: ['May', 'Jun', 'Jul', 'Aug', 'Sep'], series: [{ name: 'Models', values: [12, 18, 25, 22, 31] }, { name: 'Search', values: [3, 4, 6, 5, 8] }] }),
  card('c2', 'chart', { chart: 'donut', title: 'Where the budget goes', labels: ['Haiku', 'Sonnet', 'Search', 'Browser'], series: [{ name: 'Share', values: [52, 28, 12, 8] }], unit: '$' }),
  card('p1', 'comparison', { title: 'Which paddle fits you?', bestIndex: 0, items: [{ name: 'Selkirk Vanguard', price: '$89.99', badge: 'Best value', facts: [{ label: 'Weight', value: '7.9 oz' }, { label: 'Core', value: 'Polypropylene' }], pros: ['Great control', 'Cheap'], cons: ['Less power'], link: 'https://example.com/a' }, { name: 'JOOLA Ben Johns', price: '$129', facts: [{ label: 'Weight', value: '8.2 oz' }, { label: 'Core', value: 'Carbon' }], pros: ['Power'], cons: ['Pricey'], link: 'https://example.com/b' }, { name: 'CRBN 1', price: '$199.95', facts: [{ label: 'Weight', value: '8.0 oz' }], pros: ['Spin'], cons: ['Expensive', 'Stiff'] }] }),
];
const json = (res, status, body) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(body)); };
const body = req => new Promise(r => { let d = ''; req.on('data', c => d += c); req.on('end', () => { try { r(JSON.parse(d || '{}')); } catch { r({}); } }); });

http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x'); const p = url.pathname;
  if (p === '/_m') { res.writeHead(200, { 'Content-Type': 'text/html' }); return res.end('<body style="margin:0;background:#222"><iframe src="/app/" style="width:390px;height:844px;border:0;background:#000"></iframe></body>'); }
  if (p === '/') { res.writeHead(200, { 'Content-Type': 'text/html' }); return res.end(await readFile(join(DIST, 'index.html'))); }   // mimics the edge showing the app at the site root
  if (p === '/v1/csrf') return json(res, 200, { csrf_token: 'mock', api_version: 'mock' });
  if (p === '/readyz') return json(res, 200, { foundation_ready: true });
  if (p === '/auth/login') { signedIn = true; return json(res, 200, { ok: true }); }
  if (p === '/auth/logout') { signedIn = false; return json(res, 200, { ok: true }); }
  if (p.startsWith('/v1/')) {
    if (!signedIn) return json(res, 401, { error: 'authentication_required' });
    if (p === '/v1/app') return json(res, 200, { api_version: 'mock', user: { email: 'parsa@example.com', role: 'customer' }, assistant: { state: 'ready' },
      features: { chat: true, execution: true, files: false, uploads: false, telegram: false, connectors: false, billing_mode: 'open', requests: true, usage: true }, limits: { max_message_chars: 16000 } });
    if (p === '/v1/requests') return json(res, 200, { requests });
    if (p === '/v1/conversations' && req.method === 'POST') return json(res, 201, { conversation: { id: 'cnew', project_id: 'p1' } });
    if (p === '/v1/conversations') return json(res, 200, { conversations: [
      { id: 'c1', project_id: 'p1', created_at: new Date().toISOString(), title: 'Search for the best cheap carbon pickleball rackets', last_activity: new Date().toISOString(), active: 1 },
      { id: 'c2', project_id: 'p1', created_at: new Date(Date.now() - 86400000).toISOString(), title: 'What is 17 times 3?', last_activity: new Date(Date.now() - 86400000).toISOString(), active: 0 },
      { id: 'c3', project_id: 'p1', created_at: '2026-09-20T10:00:00Z', title: 'Build me an e-commerce website', last_activity: '2026-09-20T10:05:00Z', active: 0 }] });
    if (p.endsWith('/blocks')) return json(res, 200, { blocks: [
      { id: 'b1', conversation_id: 'c1', anchor_message_id: 1, kind: 'form', schema_version: '1.0', version: 3, status: 'draft', launched_request_id: null,
        spec: { schemaVersion: '1.0', type: 'form', title: 'Shape your website', description: 'A few choices that change the plan.', submit: { label: 'Create the plan', action: 'submit_requirements' }, fields: [
          { id: 'kind', type: 'segmented', label: 'What kind of website?', required: true, default: 'ecommerce', options: [{ label: 'Business', value: 'business' }, { label: 'E-commerce', value: 'ecommerce' }, { label: 'Portfolio', value: 'portfolio' }, { label: 'SaaS', value: 'saas' }] },
          { id: 'style', type: 'segmented', label: 'Visual style', default: 'futuristic', options: [{ label: 'Minimal', value: 'minimal' }, { label: 'Modern', value: 'modern' }, { label: 'Futuristic', value: 'futuristic' }] },
          { id: 'accounts', type: 'toggle', label: 'Include user accounts and sign-in', default: true },
          { id: 'payments', type: 'select', label: 'Payment provider', default: 'stripe', showIf: { field: 'kind', equals: 'ecommerce' }, options: [{ label: 'Stripe', value: 'stripe' }, { label: 'PayPal', value: 'paypal' }] },
          { id: 'catalog', type: 'slider', label: 'Products in the first catalog', min: 1, max: 500, step: 1, default: 40, unit: 'items', showIf: { field: 'kind', equals: 'ecommerce' } }] },
        state: { answers: {} } },
      { id: 'b2', conversation_id: 'c1', anchor_message_id: 2, kind: 'task_plan', schema_version: '1.0', version: 2, status: 'draft', launched_request_id: null,
        spec: PLAN, state: { plan: PLAN, requirements: {}, revision: 1 } }, ...CARDS] });
    if (p.endsWith('/state')) { const b = await body(req); return json(res, 200, { block: { version: (b.version || 1) + 1 } }); }
    if (p.endsWith('/messages')) return json(res, 200, { messages: [{ id: 1, request_id: 'r4', provenance: 'customer', content: 'Search for the best cheap carbon pickleball rackets for me and rank the top 10', created_at: 'x' }, { id: 2, request_id: 'r4', provenance: 'agent', content: 'I\'ll start by searching the web for current options.', created_at: 'x' }], tasks: [{ id: 'r4', state: 'running', created_epoch: now() - 140 }] });
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
