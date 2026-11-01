// The extension's service worker: the Chrome side of the "hands". It owns the tabs Lumina works in (a "Lumina" tab group), attaches DevTools to those tabs only,
// and carries the runner protocol between the platform (over one outbound WebSocket) and ./executor.js. Nothing runs unless the customer has switched it on
// (the toolbar button), and the "is debugging this browser" bar Chrome shows on those tabs is their stop button.
import { Executor } from './executor.js';
import { MAX_PAGES } from './rules.js';
import { PROD_BRIDGE, LUMINA_ORIGIN, PROD_PANEL_API, bridgeAllowed, panelApiAllowed, normalisePairCode } from './config.js';
import { createPanelLink } from './panel-link.js';

const PING_MS = 20_000, RETRY_MS = [1000, 2000, 5000, 15000];

// The side panel's ticket and calls (panel-link.js): kept here so the panel page never holds the ticket. The address follows the same rule as the bridge.
const panelLink = createPanelLink({
  base: async () => { const { panelApi } = await chrome.storage.local.get('panelApi'); return panelApiAllowed(panelApi) ? panelApi : PROD_PANEL_API; },
  isOn: () => enabled,
  onChange: () => { try { chrome.runtime.sendMessage({ type: 'panel:changed' })?.catch?.(() => {}); } catch { /* no panel is open */ } },
});
const panelOptions = (tabId, enabledForTab) => { try { return chrome.sidePanel?.setOptions({ tabId, ...(enabledForTab ? { path: 'panel.html', enabled: true } : { enabled: false }) })?.catch?.(() => {}); } catch { /* an older Chrome: no side panel */ } };

let owned = [], group = null, onEvent = () => {}, executor = null, ws = null, enabled = false, attempt = 0, pinger = null, queue = Promise.resolve();

// ------------------------------------------------------------------------------------------------------------ the tabs (the executor's `host`)
async function adopt(tabId) {
  await chrome.debugger.attach({ tabId }, '1.3');
  owned.push(tabId);
  panelOptions(tabId, true);      // the side chat exists on the tabs Lumina works in, and nowhere else
  try {
    group = await chrome.tabs.group(group === null ? { tabIds: [tabId] } : { tabIds: [tabId], groupId: group });
    await chrome.tabGroups.update(group, { title: 'Lumina', color: 'purple' });
  } catch { /* the group is a courtesy; the work does not depend on it */ }
  await executor.adopt(tabId);
}

function forget(tabId) { if (owned.includes(tabId)) panelOptions(tabId, false); owned = owned.filter(t => t !== tabId); if (!owned.length) group = null; }

const host = {
  tabs: () => [...owned],
  async newTab() { const t = await chrome.tabs.create({ url: 'about:blank', active: true }); await adopt(t.id); return t.id; },
  async closeTab(tabId) { forget(tabId); try { await chrome.debugger.detach({ tabId }); } catch { /* already detached */ } try { await chrome.tabs.remove(tabId); } catch { /* already closed */ } },
  send: (tabId, method, params) => chrome.debugger.sendCommand({ tabId }, method, params),
  onEvent: fn => { onEvent = fn; },
  activate: tabId => chrome.tabs.update(tabId, { active: true }),
};

chrome.debugger.onEvent.addListener((source, method, params) => { if (owned.includes(source.tabId)) onEvent(source.tabId, method, params); });

// The customer pressed "Cancel" on Chrome's debugging bar: that is a stop, for the whole session.
chrome.debugger.onDetach.addListener((source, reason) => {
  if (!owned.includes(source.tabId)) return;
  forget(source.tabId);
  if (reason === 'canceled_by_user') stop('stopped_by_customer');
});

chrome.tabs.onRemoved.addListener(tabId => forget(tabId));

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
  badge('ON', '#7c3aed', 'Lumina: on. Click to stop.');
  connect();
}

async function stop(reason = 'stopped') {
  if (!enabled && !ws) return;
  enabled = false; clearInterval(pinger);
  panelLink.clear();      // switched off: the side chat loses its credential at once
  await chrome.storage.local.set({ enabled: false });
  say({ event: 'stopped', reason });
  try { ws?.close(1000, reason); } catch { /* gone */ }
  ws = null;
  for (const t of [...owned]) await host.closeTab(t);
  executor = null;
  badge('', '#000000', 'Lumina: off. Click to allow.');
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
  };
  socket.onmessage = e => {
    let msg; try { msg = JSON.parse(e.data); } catch { msg = null; }
    if (panelLink.push(msg)) return;      // a side-panel ticket is not a browser command: it must not wait behind one
    queue = queue.then(() => run(e.data));      // one command at a time, in order, as the runner does
  };
  socket.onclose = async e => {
    if (ws !== socket) return;
    ws = null; clearInterval(pinger);
    panelLink.clear();      // the link is gone: so is the side chat's credential (the platform hands a fresh one over once we are back)
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
    return;
  }
  if (!msg || typeof msg !== 'object' || msg.cmd === undefined) return;      // pongs and other chatter
  try { reply = await executor.handle(msg); } catch (e) { reply = { ok: false, error: 'runner_error' }; }
  say({ ...reply, id: msg.id });
}

function say(obj) { try { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); } catch { /* the link dropped; the retry picks it up */ } }

function badge(text, color, title) { chrome.action.setBadgeText({ text }); chrome.action.setBadgeBackgroundColor({ color }); chrome.action.setTitle({ title }); }

// ------------------------------------------------------------------------------------------------------------ the toolbar popup and the Lumina page
async function status() {
  const { token = '', pairCode = '' } = await chrome.storage.local.get(['token', 'pairCode']);
  return { enabled, connected: !!ws && ws.readyState === 1, paired: !!token, pairing: !!pairCode, tabs: [...owned], panel: panelLink.has() };
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

async function onPopup(msg) {
  if (msg?.type === 'status') return status();
  if (msg?.type === 'toggle') { await (enabled ? stop('stopped_by_customer') : start()); return status(); }
  if (msg?.type === 'pair') return pair(msg.code);
  if (msg?.type === 'panel:state') { const s = await status(); return { enabled: s.enabled, connected: s.connected, hasTicket: s.panel }; }
  if (msg?.type === 'panel:call') return panelLink.call(msg.endpoint, msg.input);
  return { ok: false, error: 'unknown_message' };
}

// Only this extension's own popup...
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

// The worker is stopped and restarted by Chrome; tabs from before a restart are not ours to resume, so a restart always begins switched off.
chrome.storage.local.set({ enabled: false });
