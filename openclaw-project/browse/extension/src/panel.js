// The side panel page: a chat with Lumina on every tab. Opening it starts a new session (a new conversation, the assistant begins waking); a message starts a task, in a new tab, in
// the tab you are on, or in another open tab you allowed. It holds no credential: every call goes through the service worker, which holds the ticket and the device token.
// Everything from the network or from a page is shown with textContent, never as markup.
import { view, stepLine, mergeEvents, pollDelay, errorText, newKey, buildContext, availableActions, cleanPrompts, QUICK_ACTIONS, restrictedUrl } from './panel-model.js';

const $ = id => document.getElementById(id);
let windowId = null;
const ask = message => chrome.runtime.sendMessage({ ...message, windowId });
const call = (endpoint, input) => ask({ type: 'panel:call', endpoint, input });

const model = {
  link: { enabled: false, connected: false, paired: false, hasTicket: false, offered: null, hasSites: false }, state: null, error: null, notice: null, sending: false, opening: false,
  trail: [], after: 0, request: null, failures: 0, draftKey: null, draftText: '', target: 'new_tab', mode: 'browse', tabs: [], picked: null, read: null, withPage: true, prompts: [], settings: false,
};
let timer = null, wakeUp = null, running = false;

// ------------------------------------------------------------------------------------------------------------ painting
function activeTab() { return model.tabs.find(t => t.active) || null; }
function contextTab() {
  if (model.target === 'tab') return model.tabs.find(t => t.id === model.picked) || null;
  return activeTab();      // "this tab" and "new tab" (page context only) both refer to the tab the customer is looking at
}

function paint() {
  const v = view({ link: model.link, state: model.state, error: model.error, sending: model.sending });
  $('status').textContent = v.headline; $('status').dataset.tone = v.tone;
  $('detail').textContent = v.detail; $('detail').hidden = !v.detail;
  const text = $('text');
  text.disabled = !v.canSend; $('send').disabled = !v.canSend; $('stop').hidden = !v.canStop;
  text.placeholder = v.canSend ? (model.target === 'new_tab' ? 'Ask or tell Lumina…' : 'Tell Lumina what to do in the tab…') : 'Connect and turn Lumina on to write here.';
  const code = model.notice || (['browser_off', 'no_ticket', 'device'].includes(model.error) ? null : model.error);
  const err = $('error'); err.hidden = !code; err.textContent = code ? errorText(code) : '';
  $('banner').hidden = !model.link.offered; if (model.link.offered) $('banner-text').textContent = 'A task from the Lumina web chat is running in this browser.';
  paintSettings(v); paintTrail(); paintMessages(); paintContext(); paintQuick();
}

function paintSettings(v) {
  $('settings').hidden = !model.settings && !v.needsPair;
  $('pair').hidden = !(v.needsPair || !model.link.paired);
  $('gear').setAttribute('aria-expanded', String(!$('settings').hidden));
  $('power-text').textContent = model.link.enabled ? (model.link.connected ? 'Lumina is on.' : 'Lumina is on, connecting…') : 'Lumina is off.';
  $('power').textContent = model.link.enabled ? 'Turn off' : 'Turn on'; $('power').hidden = !model.link.paired;
  $('sites-text').textContent = model.link.hasSites ? 'Lumina can read the pages you ask about.' : 'Reading pages is off. Lumina only sees tab names.';
  $('sites').hidden = model.link.hasSites;
  const list = $('saved');
  list.replaceChildren(...model.prompts.map((p, i) => {
    const li = document.createElement('li'); const label = document.createElement('span'); label.textContent = p.name;
    const x = document.createElement('button'); x.type = 'button'; x.textContent = 'Remove'; x.addEventListener('click', () => { model.prompts.splice(i, 1); savePrompts(); paint(); });
    li.append(label, x); return li;
  }));
}

function paintTrail() {
  const lines = model.trail.map(stepLine).filter(Boolean).slice(-40);
  $('trail-box').hidden = lines.length === 0;
  $('trail').replaceChildren(...lines.map(line => { const li = document.createElement('li'); li.textContent = line; return li; }));
}

let shown = '';
function paintMessages() {
  const messages = model.state?.messages ?? [];
  $('empty').hidden = messages.length > 0;
  const sig = messages.map(m => m.id + ':' + m.text.length + ':' + m.surface).join(',');
  if (sig === shown) return;
  shown = sig;
  const main = $('main'); const stick = main.scrollTop + main.clientHeight >= main.scrollHeight - 40;
  $('messages').replaceChildren(...messages.map(m => {
    const li = document.createElement('li'); li.className = 'msg'; li.dataset.role = ['customer', 'agent', 'system'].includes(m.role) ? m.role : 'system';
    li.textContent = String(m.text ?? '');
    if (m.surface === 'panel' && m.role === 'customer') { const tag = document.createElement('small'); tag.textContent = 'sent from this panel'; li.append(tag); }
    return li;
  }));
  if (stick) main.scrollTop = main.scrollHeight;
}

function paintContext() {
  for (const b of document.querySelectorAll('[data-target]')) b.setAttribute('aria-pressed', String(b.dataset.target === model.target));
  for (const b of document.querySelectorAll('[data-mode]')) b.setAttribute('aria-pressed', String(b.dataset.mode === model.mode));
  const picking = model.target === 'tab';
  $('picker').hidden = !picking;
  if (picking) {
    const select = $('tabs'); const options = model.tabs.filter(t => !t.restricted).map(t => { const o = document.createElement('option'); o.value = String(t.id); o.textContent = (t.title || t.url).slice(0, 80); return o; });
    select.replaceChildren(...options);
    if (model.picked === null || !model.tabs.some(t => t.id === model.picked && !t.restricted)) model.picked = model.tabs.find(t => !t.restricted)?.id ?? null;
    if (model.picked !== null) select.value = String(model.picked);
  }
  const tab = contextTab();
  const acting = model.target !== 'new_tab';
  $('tabline').hidden = !acting || !tab;
  if (acting && tab) {
    $('tabname').textContent = tab.title || tab.url;
    $('allow').hidden = !!tab.grant || tab.restricted; $('revoke').hidden = !tab.grant;
    $('allow').disabled = !model.link.enabled || !model.link.connected;
  }
  $('withpage').parentElement.hidden = !tab;
  const note = $('ctxnote');
  const reason = !tab ? '' : tab.restricted ? 'Lumina cannot work in this kind of page.' : model.read && !model.read.read ? 'Lumina can only see this tab’s name until you allow page reading in settings.' : '';
  note.hidden = !reason; note.textContent = reason;
}

function paintQuick() {
  const read = model.read || {};
  const actions = availableActions({ hasPage: !!read.text, hasSelection: !!read.selection });
  const buttons = actions.map(a => { const b = document.createElement('button'); b.type = 'button'; b.textContent = a.label; b.disabled = !$('send') || $('send').disabled; b.addEventListener('click', () => send(a.prompt, { mode: a.mode })); return b; });
  const mine = model.prompts.map(p => { const b = document.createElement('button'); b.type = 'button'; b.textContent = p.name; b.disabled = $('send').disabled; b.addEventListener('click', () => { $('text').value = p.text; $('text').focus(); }); return b; });
  $('quick').replaceChildren(...buttons, ...mine);
}

// ------------------------------------------------------------------------------------------------------------ talking to the worker and the platform
async function refreshLink() {
  try { model.link = { ...model.link, ...(await ask({ type: 'panel:state' })) }; } catch { /* the worker is restarting */ }
}

async function startSession(fresh) {
  if (model.opening) return;
  model.opening = true; model.error = null; model.notice = null;
  if (fresh) { model.state = null; model.trail = []; model.after = 0; model.request = null; shown = ''; }
  paint();
  try {
    const out = await ask({ type: fresh ? 'panel:new' : 'panel:open' });
    if (out && !out.ok) model.error = out.error === 'unpaired' ? null : out.error === 'connecting' ? null : out.error;
    await refreshLink();
  } catch { model.error = 'unavailable_now'; } finally { model.opening = false; }
}

async function refresh() {
  await refreshLink();
  if (model.link.paired && !model.link.hasTicket && !model.opening && model.error !== 'device') {
    if (model.link.enabled || !model.state) await startSession(false);
  }
  if (!model.link.enabled || !model.link.connected || !model.link.hasTicket) { model.state = model.link.hasTicket ? model.state : null; model.failures = 0; return; }
  const out = await call('state');
  if (out.status === 200) {
    model.state = out.data; model.error = null; model.failures = 0;
    const id = out.data.request?.id ?? null;
    if (id !== model.request) { model.request = id; model.after = 0; model.trail = []; }
    if (id) await refreshEvents(id);
  } else {
    model.error = out.data?.error ?? 'unavailable_now';
    if (!['browser_off', 'no_ticket', 'ticket', 'device'].includes(model.error)) model.failures += 1;
  }
}

async function refreshEvents(id) {
  const out = await call('events', { request: id, after: model.after, limit: 100 });
  if (out.status !== 200) return;
  const rows = out.data.events ?? [];
  if (rows.length) { model.trail = mergeEvents(model.trail, rows); model.after = model.trail[model.trail.length - 1].sequence; }
}

async function refreshTabs() {
  try { const out = await ask({ type: 'tabs:list' }); if (out?.ok) model.tabs = out.tabs; } catch { /* worker restarting */ }
  const tab = contextTab();
  model.read = tab ? await ask({ type: 'tab:read', tabId: tab.id }).catch(() => null) : null;
}

async function loop() {
  if (running) return;
  running = true;
  try {
    for (;;) {
      try { await refresh(); await refreshTabs(); } catch { model.failures += 1; }
      paint();
      await new Promise(r => { wakeUp = r; timer = setTimeout(r, pollDelay({ live: !!model.state?.live, failures: model.failures, hidden: document.hidden })); });
    }
  } finally { running = false; }
}
const wake = () => { clearTimeout(timer); wakeUp?.(); };      // look again now instead of waiting out the delay

// ------------------------------------------------------------------------------------------------------------ sending
async function send(text, { mode } = {}) {
  const message = String(text ?? '').trim();
  if (!message || model.sending) return;
  model.notice = null; model.sending = true; paint();
  try {
    const tab = contextTab(); const acting = model.target !== 'new_tab';
    if (acting && (!tab || tab.restricted || !tab.grant)) { model.notice = 'bad_tab'; return; }
    if (acting && !model.link.enabled) { model.notice = 'browser_off'; return; }
    const read = tab ? await ask({ type: 'tab:read', tabId: tab.id }).catch(() => null) : null;
    const context = buildContext({
      target: model.target, tabs: tab ? [{ title: read?.title ?? tab.title, url: read?.url ?? tab.url, grant: tab.grant ?? undefined }] : [],
      selection: read?.selection ?? '', page: model.withPage ? read?.text ?? '' : '',
    });
    if (message !== model.draftText || !model.draftKey) { model.draftText = message; model.draftKey = newKey(); }
    const out = await call('send', { message, key: model.draftKey, mode: acting ? 'browse' : (mode ?? model.mode), context });
    if (out.status === 202) { model.draftKey = null; model.draftText = ''; $('text').value = ''; model.error = null; await refresh(); }
    else model.notice = out.data?.error ?? 'unavailable_now';
  } finally { model.sending = false; paint(); wake(); }
}

// ------------------------------------------------------------------------------------------------------------ the controls
const savePrompts = () => chrome.storage.local.set({ prompts: model.prompts });
const saveUi = () => { const ui = { target: model.target, mode: model.mode, withPage: model.withPage }; return chrome.storage.local.set({ ui: ui }); };

$('composer').addEventListener('submit', e => { e.preventDefault(); send($('text').value); });
$('text').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send($('text').value); } });
$('stop').addEventListener('click', async () => { const out = await call('stop'); model.notice = out.status === 202 ? null : out.data?.error ?? 'unavailable_now'; paint(); wake(); });
$('new').addEventListener('click', async () => { await startSession(true); paint(); wake(); });
$('close').addEventListener('click', () => window.close());
$('gear').addEventListener('click', () => { model.settings = !model.settings; paint(); });
$('power').addEventListener('click', async () => { await ask({ type: 'toggle' }); await refreshLink(); paint(); wake(); });
$('banner-use').addEventListener('click', async () => { await ask({ type: 'panel:use-offered' }); model.state = null; model.request = null; model.trail = []; shown = ''; await refreshLink(); paint(); wake(); });
$('sites').addEventListener('click', async () => {
  try { await chrome.permissions.request({ origins: ['<all_urls>'] }); } catch { /* the customer said no, or Chrome refused */ }
  await refreshLink(); await refreshTabs(); paint();
});
$('pair').addEventListener('submit', async e => {
  e.preventDefault();
  const err = $('pair-error'); err.hidden = true;
  const reply = await ask({ type: 'pair', code: $('code').value });
  if (!reply || !reply.ok) { err.textContent = 'That is not a Lumina pairing code. It has 8 letters and numbers.'; err.hidden = false; return; }
  $('code').value = ''; model.error = null; model.settings = false; await refreshLink(); paint(); wake();
});
$('saved-form').addEventListener('submit', e => {
  e.preventDefault();
  model.prompts = cleanPrompts([...model.prompts, { name: $('saved-name').value, text: $('saved-text').value }]); savePrompts();
  $('saved-name').value = ''; $('saved-text').value = ''; paint();
});
for (const b of document.querySelectorAll('[data-target]')) b.addEventListener('click', async () => { model.target = b.dataset.target; saveUi(); await refreshTabs(); paint(); });
for (const b of document.querySelectorAll('[data-mode]')) b.addEventListener('click', () => { model.mode = b.dataset.mode; saveUi(); paint(); });
$('tabs').addEventListener('change', async e => { model.picked = Number(e.target.value); await refreshTabs(); paint(); });
$('withpage').addEventListener('change', e => { model.withPage = e.target.checked; saveUi(); });
$('allow').addEventListener('click', async () => {
  const tab = contextTab(); if (!tab) return;
  const out = await ask({ type: 'tab:grant', tabId: tab.id });
  model.notice = out?.ok ? null : out?.error ?? 'bad_tab';
  await refreshTabs(); paint();
});
$('revoke').addEventListener('click', async () => { const tab = contextTab(); if (!tab?.grant) return; await ask({ type: 'tab:revoke', grant: tab.grant }); await refreshTabs(); paint(); });

// The right-click menu leaves a prompt for this window's panel: it is put in the box for the customer to finish, never sent by itself.
async function takePrompt() {
  const out = await ask({ type: 'panel:take-prompt' }).catch(() => null);
  const p = out?.prompt; if (!p) return;
  $('text').value = p.kind === 'selection' ? `About this text: “${p.text}”\n` : p.kind === 'link' ? `About this link (${p.url}): ` : 'About this page: ';
  $('text').focus();
}
chrome.runtime.onMessage.addListener(m => {
  if (m?.type === 'panel:changed') wake();
  else if (m?.type === 'panel:prompt' && m.windowId === windowId) takePrompt();
  else if (m?.type === 'panel:close' && m.windowId === windowId) window.close();
});
for (const event of ['onActivated', 'onUpdated']) chrome.tabs?.[event]?.addListener(() => wake());

// ------------------------------------------------------------------------------------------------------------ start
(async () => {
  try { windowId = (await chrome.windows.getCurrent()).id; } catch { windowId = null; }
  try { const port = chrome.runtime.connect({ name: 'panel' }); port.postMessage({ windowId }); } catch { /* no port: the panel still works, only the shortcut cannot close it */ }
  const saved = await chrome.storage.local.get(['prompts', 'ui']).catch(() => ({}));
  model.prompts = cleanPrompts(saved.prompts);
  if (saved.ui) { if (['new_tab', 'this_tab', 'tab'].includes(saved.ui.target)) model.target = saved.ui.target; if (['browse', 'auto'].includes(saved.ui.mode)) model.mode = saved.ui.mode; if (typeof saved.ui.withPage === 'boolean') { model.withPage = saved.ui.withPage; $('withpage').checked = saved.ui.withPage; } }
  void QUICK_ACTIONS; void restrictedUrl;
  paint();
  await startSession(false);
  await takePrompt();
  loop();
})();
