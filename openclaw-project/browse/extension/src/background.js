// The extension's service worker: the Chrome side of Lumina. It owns two things.
//   1. The "hands": the tabs Lumina works in (a "Lumina" tab group it opens itself, plus any tab of the customer's own they have allowed), DevTools attached to those tabs only,
//      and the runner protocol between the platform (one outbound WebSocket) and ./executor.js. Nothing runs unless the customer has switched it on, and the "is debugging this
//      browser" bar Chrome shows on those tabs is their stop button.
//   2. The side chat: a panel on every tab where the customer talks to Lumina directly. Every time it is opened it is a new session (a new conversation, the assistant woken up),
//      signed in with this browser's own pairing, with no web page involved (panel-link.js).
import { Executor } from './executor.js';
import { MAX_PAGES, urlAllowed } from './rules.js';
import { PROD_BRIDGE, LUMINA_ORIGIN, PROD_PANEL_API, bridgeAllowed, panelApiAllowed, normalisePairCode } from './config.js';
import { createPanelLink } from './panel-link.js';
import { restrictedUrl } from './panel-model.js';

const PING_MS = 20_000, RETRY_MS = [1000, 2000, 5000, 15000], MAX_GRANTS = 8, ALL_SITES = { origins: ['<all_urls>'] };

let owned = [], group = null, onEvent = () => {}, executor = null, ws = null, enabled = false, attempt = 0, pinger = null, queue = Promise.resolve();

// ------------------------------------------------------------------------------------------------------------ the side chat's sessions (one per browser window)
const links = new Map();                 // windowId -> panel link
const openPanels = new Set();            // windowIds whose panel page is open (it connects a port while it is)
const pending = new Map();               // windowId -> a prompt the right-click menu left for the panel: { kind, text, url }
const apiBase = async () => { const { panelApi } = await chrome.storage.local.get('panelApi'); return panelApiAllowed(panelApi) ? panelApi : PROD_PANEL_API; };
const deviceToken = async () => (await chrome.storage.local.get('token')).token || '';

function linkFor(windowId) {
  const key = Number.isInteger(windowId) ? windowId : -1;
  if (!links.has(key)) links.set(key, createPanelLink({ base: apiBase, isOn: () => enabled, token: deviceToken, onChange: () => tell({ type: 'panel:changed' }) }));
  return links.get(key);
}
const tell = msg => { try { chrome.runtime.sendMessage(msg)?.catch?.(() => {}); } catch { /* no panel is open */ } };
const clearLinks = () => { for (const l of links.values()) l.clear(); };

// ------------------------------------------------------------------------------------------------------------ tabs the customer allowed (their own, left where they are)
const grants = new Map();                // grant name -> { tabId, attached }
let grantSeq = 0;
const grantedTabs = () => [...grants.values()].filter(g => g.attached).map(g => g.tabId);
const isGranted = tabId => [...grants.values()].some(g => g.tabId === tabId);
const grantOf = tabId => [...grants.entries()].find(([, g]) => g.tabId === tabId)?.[0] ?? null;

async function releaseTab(tabId) { try { await chrome.debugger.detach({ tabId }); } catch { /* already detached */ } for (const g of grants.values()) if (g.tabId === tabId) g.attached = false; }

async function grantTab(tabId) {
  if (!enabled) return { ok: false, error: 'browser_off' };
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  const { devAllowLoopback = false } = await chrome.storage.local.get('devAllowLoopback');
  if (!tab || restrictedUrl(tab.url) || !urlAllowed(tab.url, devAllowLoopback)) return { ok: false, error: 'tab_blocked' };
  const have = grantOf(tabId);
  if (have) return { ok: true, grant: have };
  if (grants.size >= MAX_GRANTS) return { ok: false, error: 'bad_tab' };
  const grant = 'g' + (++grantSeq);
  grants.set(grant, { tabId, attached: false });
  return { ok: true, grant };
}

async function revokeGrant(grant) {
  const g = grants.get(grant);
  if (!g) return { ok: true };
  grants.delete(grant);
  if (!isGranted(g.tabId)) await releaseTab(g.tabId);
  return { ok: true };
}

// ------------------------------------------------------------------------------------------------------------ the tabs (the executor's `host`)
async function adopt(tabId) {
  await chrome.debugger.attach({ tabId }, '1.3');
  owned.push(tabId);
  try {
    group = await chrome.tabs.group(group === null ? { tabIds: [tabId] } : { tabIds: [tabId], groupId: group });
    await chrome.tabGroups.update(group, { title: 'Lumina', color: 'purple' });
  } catch { /* the group is a courtesy; the work does not depend on it */ }
  await executor.adopt(tabId);
}

function forget(tabId) { owned = owned.filter(t => t !== tabId); if (!owned.length) group = null; }

const host = {
  tabs: () => [...owned, ...grantedTabs()],
  async newTab() { const t = await chrome.tabs.create({ url: 'about:blank', active: true }); await adopt(t.id); return t.id; },
  async closeTab(tabId) {
    if (isGranted(tabId)) { await releaseTab(tabId); return; }      // the customer's own tab: let go of it, never close it
    forget(tabId); try { await chrome.debugger.detach({ tabId }); } catch { /* already detached */ } try { await chrome.tabs.remove(tabId); } catch { /* already closed */ }
  },
  send: (tabId, method, params) => chrome.debugger.sendCommand({ tabId }, method, params),
  onEvent: fn => { onEvent = fn; },
  activate: tabId => chrome.tabs.update(tabId, { active: true }),
  isGranted,
  async granted(grant) {
    const g = grants.get(grant);
    if (!g) return null;
    try {
      if (!g.attached) { await chrome.debugger.attach({ tabId: g.tabId }, '1.3'); g.attached = true; }
      return g.tabId;
    } catch { return null; }
  },
};

chrome.debugger.onEvent.addListener((source, method, params) => { if (owned.includes(source.tabId) || grantedTabs().includes(source.tabId)) onEvent(source.tabId, method, params); });

// The customer pressed "Cancel" on Chrome's debugging bar: that is a stop, for the whole session (their own tabs included).
chrome.debugger.onDetach.addListener((source, reason) => {
  const ours = owned.includes(source.tabId), theirs = grantedTabs().includes(source.tabId);
  if (!ours && !theirs) return;
  if (ours) forget(source.tabId);
  for (const g of grants.values()) if (g.tabId === source.tabId) g.attached = false;
  if (reason === 'canceled_by_user') stop('stopped_by_customer');
});

chrome.tabs.onRemoved.addListener(tabId => { forget(tabId); for (const [name, g] of [...grants]) if (g.tabId === tabId) grants.delete(name); });

// A page the agent is working in opened a window (a login or payment popup): it joins the session, up to the same cap as the runner.
chrome.tabs.onCreated.addListener(tab => {
  if (!enabled || tab.openerTabId === undefined || !owned.includes(tab.openerTabId)) return;
  if (owned.length >= MAX_PAGES) { chrome.tabs.remove(tab.id).catch(() => {}); return; }
  adopt(tab.id).catch(() => {});
});

// ------------------------------------------------------------------------------------------------------------ the platform link
async function start() {
  if (enabled) return;
  const { devAllowLoopback = false } = await chrome.storage.local.get('devAllowLoopback');      // set by hand for local testing only; never by the platform
  executor = new Executor(host, { allowLoopback: devAllowLoopback });
  enabled = true; attempt = 0;
  await chrome.storage.local.set({ enabled: true });
  badge('ON', '#7c3aed', 'Lumina: on.');
  connect();
}

async function stop(reason = 'stopped') {
  if (!enabled && !ws) return;
  enabled = false; clearInterval(pinger);
  clearLinks();      // switched off: every side chat loses its credential at once
  await chrome.storage.local.set({ enabled: false });
  say({ event: 'stopped', reason });
  try { ws?.close(1000, reason); } catch { /* gone */ }
  ws = null;
  for (const t of [...owned]) await host.closeTab(t);
  for (const g of [...grants.values()]) await releaseTab(g.tabId);
  grants.clear();
  executor = null;
  badge('', '#000000', 'Lumina: off.');
  tell({ type: 'panel:changed' });
}

async function connect() {
  if (!enabled) return;
  const { bridge, token = '' } = await chrome.storage.local.get(['bridge', 'token']);
  let socket;
  try { socket = new WebSocket(bridgeAllowed(bridge) ? bridge : PROD_BRIDGE); } catch { return retry(); }      // a stored address is only used for production or this computer
  ws = socket;
  socket.onopen = async () => {
    attempt = 0;
    // A pairing code (typed or handed over by the Lumina page) wins over an old token: it is something the customer just did. The platform answers with the token.
    const { pairCode = '' } = await chrome.storage.local.get('pairCode');
    const version = chrome.runtime.getManifest().version;
    const label = `Chrome (${(await chrome.runtime.getPlatformInfo().catch(() => ({ os: '' }))).os || 'computer'})`;
    if (socket.readyState !== 1) return;
    socket.send(JSON.stringify(pairCode ? { hello: 1, pair: pairCode, label, version } : { hello: 1, token, version }));
    clearInterval(pinger);
    pinger = setInterval(() => say({ ping: Date.now() }), PING_MS);      // traffic on the socket also keeps this worker awake
    tell({ type: 'panel:changed' });
  };
  socket.onmessage = e => {
    let msg; try { msg = JSON.parse(e.data); } catch { msg = null; }
    if (msg && typeof msg === 'object' && 'panel' in msg) { for (const l of links.size ? links.values() : [linkFor(-1)]) l.push(msg); return; }      // a ticket for a web-chat task running here: not a browser command, it must not wait behind one
    queue = queue.then(() => run(e.data));      // one command at a time, in order, as the runner does
  };
  socket.onclose = async e => {
    if (ws !== socket) return;
    ws = null; clearInterval(pinger);
    clearLinks();      // the link is gone: so are the side chats' credentials (each panel asks for a fresh session once we are back)
    tell({ type: 'panel:changed' });
    if (!enabled) return;
    // 4401: not (or no longer) a paired device; 4403: revoked; 4409: another computer took over. Trying again would change nothing: switch off and say so.
    if ([4401, 4403, 4409].includes(e?.code)) { await stop(e.reason || 'refused'); badge('!', '#dc2626', `Lumina: ${e.reason || 'refused'}. Pair this browser again.`); return; }
    retry();
  };
  socket.onerror = () => {};
}

function retry() { setTimeout(connect, RETRY_MS[Math.min(attempt++, RETRY_MS.length - 1)]); }

async function run(raw) {
  let msg, reply;
  try { msg = JSON.parse(raw); } catch { return say({ ok: false, error: 'bad_json' }); }
  if (msg && msg.welcome) {      // the platform knows us; a new device is handed its token exactly once
    if (msg.token) { await chrome.storage.local.set({ token: msg.token }); await chrome.storage.local.remove('pairCode'); }
    tell({ type: 'panel:changed' });
    return;
  }
  if (!msg || typeof msg !== 'object' || msg.cmd === undefined) return;      // pongs and other chatter
  try { reply = await executor.handle(msg); } catch (e) { reply = { ok: false, error: 'runner_error' }; }
  say({ ...reply, id: msg.id });
}

function say(obj) { try { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); } catch { /* the link dropped; the retry picks it up */ } }

function badge(text, color, title) { chrome.action.setBadgeText({ text }); chrome.action.setBadgeBackgroundColor({ color }); chrome.action.setTitle({ title }); }

const connected = () => !!ws && ws.readyState === 1;
const sleep = ms => new Promise(r => setTimeout(r, ms));
async function waitConnected(ms) { for (let t = 0; t < ms && !connected(); t += 100) await sleep(100); return connected(); }

// ------------------------------------------------------------------------------------------------------------ what the panel and the page can ask
async function status() {
  const { token = '', pairCode = '' } = await chrome.storage.local.get(['token', 'pairCode']);
  return { enabled, connected: connected(), paired: !!token, pairing: !!pairCode, tabs: [...owned], granted: grantedTabs(), panel: [...links.values()].some(l => l.has()) };
}

/** A pairing code is a fresh, deliberate act of the customer (typed here, or pressed on the Lumina page), so it also switches the extension on. */
async function pair(raw) {
  const code = normalisePairCode(raw);
  if (!code) return { ok: false, error: 'bad_code' };
  await chrome.storage.local.set({ pairCode: code });
  await stop('re-pairing');
  await start();
  return { ok: true };
}

/** Opening the side chat is the customer using Lumina: switch it on if it was off, wait for the link, and start a NEW session (a new conversation; the assistant begins waking). */
async function openSession(windowId, { fresh, conversation = null }) {
  const s = await status();
  if (!s.paired && !s.pairing) return { ok: false, error: 'unpaired' };
  if (!enabled) await start();
  if (!(await waitConnected(8000))) return { ok: false, error: 'connecting' };
  const link = linkFor(windowId);
  if (fresh) link.clear();
  const out = link.has() ? { status: 200, data: { conversation: link.conversation() } } : await link.open(conversation);
  return { ok: out.status === 200, status: out.status, error: out.data?.error ?? null, conversation: out.data?.conversation ?? link.conversation(), cell: out.data?.cell ?? 'unknown' };
}

const hasAllSites = async () => { try { return await chrome.permissions.contains(ALL_SITES); } catch { return false; } };

/** The window's tabs, for the picker: what each is called and where it is, and whether the customer already allowed Lumina to work in it. */
async function listTabs(windowId) {
  const tabs = await chrome.tabs.query(Number.isInteger(windowId) ? { windowId } : { currentWindow: true });
  return tabs.filter(t => Number.isInteger(t.id) && !String(t.url || '').startsWith(`chrome-extension://${chrome.runtime.id}`)).slice(0, 60)
    .map(t => ({ id: t.id, title: String(t.title || '').slice(0, 200), url: String(t.url || '').slice(0, 2000), active: !!t.active, favicon: typeof t.favIconUrl === 'string' && t.favIconUrl.startsWith('http') ? t.favIconUrl : '',
      grant: grantOf(t.id), restricted: restrictedUrl(t.url) }));
}

/** What a tab shows, for a message about it: its name and address always; its selected text and its text when the customer allowed Lumina to read pages. */
async function readTab(tabId) {
  const tab = await chrome.tabs.get(tabId).catch(() => null);
  if (!tab) return { ok: false, error: 'bad_tab' };
  const base = { ok: true, title: String(tab.title || '').slice(0, 200), url: String(tab.url || '').slice(0, 2000), selection: '', text: '', read: false, grant: grantOf(tabId) };
  if (restrictedUrl(tab.url) || !(await hasAllSites())) return base;
  try {
    const [result] = await chrome.scripting.executeScript({ target: { tabId }, func: () => ({ selection: String(getSelection() || ''), text: String(document.body?.innerText || '') }) });
    return { ...base, selection: String(result?.result?.selection || '').slice(0, 4000), text: String(result?.result?.text || '').slice(0, 20000), read: true };
  } catch { return base; }
}

async function onPopup(msg) {
  if (msg?.type === 'status') return status();
  if (msg?.type === 'toggle') { await (enabled ? stop('stopped_by_customer') : start()); return status(); }
  if (msg?.type === 'pair') return pair(msg.code);
  if (msg?.type === 'panel:state') {
    const s = await status(); const link = linkFor(msg.windowId);
    return { enabled: s.enabled, connected: s.connected, paired: s.paired, hasTicket: link.has(), conversation: link.conversation(), offered: link.offered(), hasSites: await hasAllSites() };
  }
  if (msg?.type === 'panel:open') return openSession(msg.windowId, { fresh: false });
  if (msg?.type === 'panel:new') return openSession(msg.windowId, { fresh: true });
  if (msg?.type === 'panel:resume') return typeof msg.conversation === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(msg.conversation) ? openSession(msg.windowId, { fresh: true, conversation: msg.conversation }) : { ok: false, error: 'invalid_request' };
  if (msg?.type === 'panel:use-offered') return { ok: linkFor(msg.windowId).useOffered() };
  if (msg?.type === 'panel:call') return linkFor(msg.windowId).call(msg.endpoint, msg.input);
  if (msg?.type === 'tabs:list') return { ok: true, tabs: await listTabs(msg.windowId) };
  if (msg?.type === 'tab:read') return Number.isInteger(msg.tabId) ? readTab(msg.tabId) : { ok: false, error: 'bad_tab' };
  if (msg?.type === 'tab:grant') return Number.isInteger(msg.tabId) ? grantTab(msg.tabId) : { ok: false, error: 'bad_tab' };
  if (msg?.type === 'tab:revoke') return typeof msg.grant === 'string' ? revokeGrant(msg.grant) : { ok: false, error: 'bad_tab' };
  if (msg?.type === 'panel:take-prompt') { const p = pending.get(msg.windowId) ?? null; pending.delete(msg.windowId); return { ok: true, prompt: p }; }
  return { ok: false, error: 'unknown_message' };
}

// The side panel's pages connect a port while they are open: that is how the worker knows which windows have one (the keyboard shortcut toggles it) and when a session is over.
chrome.runtime.onConnect.addListener(port => {
  if (port.sender?.id !== chrome.runtime.id || port.name !== 'panel') return;
  let windowId = null;
  port.onMessage.addListener(m => { if (Number.isInteger(m?.windowId)) { windowId = m.windowId; openPanels.add(windowId); } });
  port.onDisconnect.addListener(() => { if (windowId !== null) { openPanels.delete(windowId); links.get(windowId)?.clear(); links.delete(windowId); } });      // closing the panel ends its session
});

// Only this extension's own pages...
chrome.runtime.onMessage.addListener((msg, sender, respond) => {
  if (sender.id !== chrome.runtime.id) return false;
  onPopup(msg).then(respond, () => respond({ ok: false, error: 'failed' }));
  return true;
});

// ...and the Lumina web page (nothing else: manifest.json names its address too) may talk to it. The page can hand over a pairing code and nothing more: not an address
// to connect to, not a command, not a switch. The code only works if the platform issued it to the signed-in customer minutes ago.
chrome.runtime.onMessageExternal.addListener((msg, sender, respond) => {
  if (sender.origin !== LUMINA_ORIGIN || msg?.type !== 'pair') return false;
  pair(msg.code).then(respond, () => respond({ ok: false, error: 'failed' }));
  return true;
});

// ------------------------------------------------------------------------------------------------------------ opening and closing the panel: the toolbar button, the shortcut, the right-click menu
async function openPanel(windowId) { try { await chrome.sidePanel.open({ windowId }); return true; } catch { return false; } }
async function closePanel(windowId) {
  try { if (chrome.sidePanel.close) { await chrome.sidePanel.close({ windowId }); return; } } catch { /* fall back to asking the page */ }
  tell({ type: 'panel:close', windowId });
}

try {
  chrome.sidePanel?.setPanelBehavior?.({ openPanelOnActionClick: true })?.catch?.(() => {});      // the toolbar button opens the panel on any tab
  chrome.sidePanel?.setOptions?.({ path: 'panel.html', enabled: true })?.catch?.(() => {});
} catch { /* an older Chrome: the shortcut and the right-click menu still open it */ }

chrome.commands?.onCommand.addListener(async (command, tab) => {
  if (command !== 'toggle-panel' || !tab || !Number.isInteger(tab.windowId)) return;
  if (openPanels.has(tab.windowId)) await closePanel(tab.windowId); else await openPanel(tab.windowId);
});

const MENU = [['ask-selection', 'selection', 'Ask Lumina about “%s”'], ['ask-page', 'page', 'Ask Lumina about this page'], ['ask-link', 'link', 'Ask Lumina about this link']];
chrome.runtime.onInstalled?.addListener(() => {
  try { chrome.contextMenus?.removeAll(() => { for (const [id, context, title] of MENU) chrome.contextMenus.create({ id, title, contexts: [context] }); }); } catch { /* menus are a convenience */ }
});
chrome.contextMenus?.onClicked.addListener(async (info, tab) => {
  if (!tab || !Number.isInteger(tab.windowId)) return;
  const kind = String(info.menuItemId).replace('ask-', '');
  pending.set(tab.windowId, { kind, text: String(info.selectionText || info.linkUrl || '').slice(0, 4000), url: String(info.linkUrl || tab.url || '').slice(0, 2000) });
  await openPanel(tab.windowId);      // a click of the customer's own, which Chrome requires to open it
  tell({ type: 'panel:prompt', windowId: tab.windowId });
});

// The worker is stopped and restarted by Chrome; tabs from before a restart are not ours to resume, so a restart always begins switched off.
chrome.storage.local.set({ enabled: false });
