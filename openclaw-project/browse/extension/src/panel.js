// The side panel page: the run's activity and the chat, beside the tab Lumina is working in. It holds no credential: every call goes through the service worker, which
// holds the ticket. Everything from the network is shown with textContent, never as markup.
import { view, stepLine, mergeEvents, pollDelay, errorText, newKey } from './panel-model.js';

const $ = id => document.getElementById(id);
const ask = message => chrome.runtime.sendMessage(message);
const call = (endpoint, input) => ask({ type: 'panel:call', endpoint, input });

const model = { link: { enabled: false, connected: false, hasTicket: false }, state: null, error: null, notice: null, sending: false, trail: [], after: 0, request: null, failures: 0, draftKey: null, draftText: '' };
let timer = null, running = false;

function paint() {
  const v = view(model);
  $('status').textContent = v.headline; $('status').dataset.tone = v.tone;
  $('detail').textContent = v.detail; $('detail').hidden = !v.detail;
  const text = $('text');
  text.disabled = !v.canSend; $('send').disabled = !v.canSend; $('stop').hidden = !v.canStop;
  text.placeholder = v.canSend ? 'Tell it what to do differently…' : 'You can write here while a task is running.';
  // What the last send or stop answered stays until the customer types again or succeeds; what polling saw comes and goes by itself.
  const code = model.notice || (['browser_off', 'no_ticket'].includes(model.error) ? null : model.error);
  const err = $('error'); err.hidden = !code; err.textContent = code ? errorText(code) : '';
  paintTrail(); paintMessages();
}

function paintTrail() {
  const list = $('trail'); const lines = model.trail.map(stepLine).filter(Boolean).slice(-40);
  $('trail-empty').hidden = lines.length > 0;
  list.replaceChildren(...lines.map(line => { const li = document.createElement('li'); li.textContent = line; return li; }));
}

let shown = '';
function paintMessages() {
  const messages = model.state?.messages ?? [];
  const sig = messages.map(m => m.id + ':' + m.text.length + ':' + m.surface).join(',');
  if (sig === shown) return;
  shown = sig;
  const list = $('messages'); const stick = list.parentElement.parentElement.scrollTop + list.parentElement.parentElement.clientHeight >= list.parentElement.parentElement.scrollHeight - 40;
  list.replaceChildren(...messages.map(m => {
    const li = document.createElement('li'); li.className = 'msg'; li.dataset.role = ['customer', 'agent', 'system'].includes(m.role) ? m.role : 'system';
    li.textContent = String(m.text ?? '');
    if (m.surface === 'panel') { const tag = document.createElement('small'); tag.textContent = 'sent from this panel'; li.append(tag); }
    return li;
  }));
  if (stick) list.parentElement.parentElement.scrollTop = list.parentElement.parentElement.scrollHeight;
}

async function refresh() {
  model.link = await ask({ type: 'panel:state' }).catch(() => model.link) ?? model.link;
  if (!model.link.enabled || !model.link.connected || !model.link.hasTicket) { model.state = model.link.hasTicket ? model.state : null; model.error = null; model.failures = 0; return; }
  const out = await call('state');
  if (out.status === 200) {
    model.state = out.data; model.error = null; model.failures = 0;
    const id = out.data.request?.id ?? null;
    if (id !== model.request) { model.request = id; model.after = 0; model.trail = []; }
    if (id) await refreshEvents(id);
  } else {
    model.error = out.data?.error ?? 'unavailable_now';
    if (!['browser_off', 'no_ticket', 'ticket'].includes(model.error)) model.failures += 1;
  }
}

async function refreshEvents(id) {
  const out = await call('events', { request: id, after: model.after, limit: 100 });
  if (out.status !== 200) return;
  const rows = out.data.events ?? [];
  if (rows.length) { model.trail = mergeEvents(model.trail, rows); model.after = model.trail[model.trail.length - 1].sequence; }
}

async function loop() {
  if (running) return;
  running = true;
  try { await refresh(); } catch { model.failures += 1; }
  paint();
  running = false;
  clearTimeout(timer);
  timer = setTimeout(loop, pollDelay({ live: !!model.state?.live, failures: model.failures, hidden: document.hidden }));
}
const soon = () => { clearTimeout(timer); timer = setTimeout(loop, 50); };

$('composer').addEventListener('submit', async e => {
  e.preventDefault();
  const text = $('text').value.trim();
  if (!text || model.sending) return;
  if (model.draftText !== text) { model.draftText = text; model.draftKey = newKey(); }      // the same text pressed twice is the same send; new text is a new one
  model.sending = true; paint();
  const out = await call('send', { message: text, key: model.draftKey });
  model.sending = false;
  if (out.status === 202) { $('text').value = ''; model.draftText = ''; model.draftKey = null; model.notice = null; }
  else model.notice = out.data?.error ?? 'unavailable_now';
  paint(); soon(); $('text').focus();
});
$('text').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); $('composer').requestSubmit(); } });
$('stop').addEventListener('click', async () => {
  $('stop').disabled = true;
  const out = await call('stop');
  $('stop').disabled = false;
  model.notice = out.status === 202 ? null : out.data?.error ?? 'unavailable_now';
  paint(); soon();
});
$('text').addEventListener('input', () => { if (model.notice) { model.notice = null; paint(); } });
chrome.runtime.onMessage.addListener(msg => { if (msg?.type === 'panel:changed') soon(); });
document.addEventListener('visibilitychange', () => { if (!document.hidden) soon(); });
loop();
