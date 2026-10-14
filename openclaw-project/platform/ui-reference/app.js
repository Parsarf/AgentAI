// Reference client for the AgentAI account API. No framework, no inline code (the shell's policy forbids it).
// Everything it knows comes from /v1; copy the api() helper and the endpoints, not the look.
'use strict';
const root = document.getElementById('root');
let csrf = null, state = { conversation: null, poll: null };

async function api(method, path, body) {
  if (!csrf) csrf = (await (await fetch('/v1/csrf', { credentials: 'same-origin' })).json()).csrf_token;
  const res = await fetch(path, {
    method, credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let data = {}; try { data = await res.json(); } catch (e) { /* empty body */ }
  if (!res.ok) { const err = new Error(data.error || ('http_' + res.status)); err.status = res.status; throw err; }
  return data;
}
function el(tag, props = {}, ...kids) {
  const node = Object.assign(document.createElement(tag), props);
  for (const k of kids.flat()) node.append(k);
  return node;
}
function show(...nodes) { root.replaceChildren(el('div', { className: 'wrap' }, ...nodes)); }

function loginView(message) {
  const email = el('input', { type: 'email', name: 'email', autocomplete: 'username', required: true, placeholder: 'Email' });
  const password = el('input', { type: 'password', name: 'password', autocomplete: 'current-password', required: true, placeholder: 'Password' });
  const form = el('form', {}, el('h1', { textContent: 'Sign in' }), email, password, el('button', { textContent: 'Sign in' }),
    el('div', { className: 'err', textContent: message || '' }));
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try { await api('POST', '/auth/login', { email: email.value, password: password.value }); csrf = null; void start(); }
    catch (e) { loginView(e.status === 429 ? 'Too many attempts. Wait a few minutes.' : 'Those details did not work.'); }
  });
  show(form);
}

async function chatView(app) {
  clearInterval(state.poll);
  let conversations = (await api('GET', '/v1/conversations')).conversations;
  if (!conversations.length) {
    const projects = (await api('GET', '/v1/projects')).projects;
    conversations = [(await api('POST', '/v1/conversations', { project_id: projects[0].id })).conversation];
  }
  state.conversation = state.conversation && conversations.some(c => c.id === state.conversation) ? state.conversation : conversations[conversations.length - 1].id;
  const id = state.conversation;
  const page = await api('GET', '/v1/conversations/' + id + '/messages');
  const live = app.features.execution;
  const thread = el('div', {}, page.messages.map(m => el('div', { className: 'msg ' + (m.provenance === 'agent' ? 'agent' : 'customer') },
    el('div', { className: 'meta', textContent: m.provenance === 'agent' ? 'Assistant' : 'You' }), m.content)));
  const working = page.tasks.some(t => ['waiting', 'starting', 'running', 'uncertain'].includes(t.state));
  const box = el('textarea', { rows: 3, maxLength: 16000, required: true, placeholder: 'Message…' });
  const send = el('form', {}, box, el('button', { textContent: 'Send' }));
  send.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    try { await api('POST', '/v1/conversations/' + id + '/send', { message: box.value, key: crypto.randomUUID().replace(/-/g, '') }); void chatView(app); }
    catch (e) { alert(e.message); }          // a real UI would show budget_denied / queue_full as friendly text
  });
  const clear = el('button', { className: 'ghost', textContent: 'Clear conversation' });
  clear.addEventListener('click', async () => { await api('POST', '/v1/conversations/' + id + '/archive', {}); state.conversation = null; void chatView(app); });
  show(header(app), el('p', { className: 'meta', textContent: live ? (working ? 'Working… this refreshes by itself.' : 'Your assistant is live.') : 'Execution is off: messages wait.' }),
    thread, send, clear);
  if (working) state.poll = setInterval(() => chatView(app), 4000);
}

function header(app) {
  const out = el('button', { className: 'ghost', textContent: 'Sign out' });
  out.addEventListener('click', async () => { await api('POST', '/auth/logout', {}); csrf = null; void start(); });
  return el('header', {}, el('strong', { textContent: 'Reference dashboard' }), el('span', { className: 'meta', textContent: app.user.email }), out);
}

async function start() {
  try { void chatView(await api('GET', '/v1/app')); }
  catch (e) { if (e.status === 401) loginView(); else show(el('p', { className: 'err', textContent: 'Could not load (' + e.message + ').' })); }
}
void start();
