// What the side panel shows and sends, as plain data in and plain data out, so it can be tested without a browser. Nothing here touches the page or the network.

/** The ticket the platform hands over (see platform/agentai_platform/panel/ticket.py): shaped like p1.<body>.<signature>, never looked inside. */
export const TICKET = /^p1\.[A-Za-z0-9_-]{1,500}\.[A-Za-z0-9_-]{1,100}$/;
const IDENT = /^[A-Za-z0-9_-]{1,64}$/;

/** A message from the platform on the device link -> { type: 'ticket', ticket, conversation, expiresAt } | null (anything else is ignored). */
export function parsePush(panel, now = Date.now()) {
  if (!panel || typeof panel !== 'object' || typeof panel.conversation_id !== 'string' || !IDENT.test(panel.conversation_id)) return null;
  const { ticket, expires_in: life } = panel;
  if (typeof ticket !== 'string' || !TICKET.test(ticket) || !Number.isInteger(life) || life < 1 || life > 600) return null;
  return { type: 'ticket', ticket, conversation: panel.conversation_id, expiresAt: now + life * 1000 };
}

/** The platform's answer to POST /session -> { ticket, conversation, expiresAt, cell } | null when it is not shaped like one. */
export function parseSession(data, now = Date.now()) {
  if (!data || typeof data !== 'object') return null;
  const { ticket, conversation, expires_in: life, cell } = data;
  if (typeof ticket !== 'string' || !TICKET.test(ticket) || typeof conversation !== 'string' || !IDENT.test(conversation) || !Number.isInteger(life) || life < 1 || life > 600) return null;
  return { ticket, conversation, expiresAt: now + life * 1000, cell: CELLS.includes(cell) ? cell : 'unknown' };
}

export const CELLS = ['ready', 'waking', 'asleep', 'unknown'];

export const KEY = /^[A-Za-z0-9_-]{8,64}$/;
/** A fresh idempotency key for one send: pressing Send twice for the same text must not send twice, a new text must. */
export function newKey(random = globalThis.crypto) {
  const bytes = new Uint8Array(12); random.getRandomValues(bytes);
  return 'p' + [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
}

export const MAX_MESSAGE = 16000;
export const MODES = ['auto', 'browse', 'text'];
export const TARGETS = ['new_tab', 'this_tab', 'tab'];
const cut = (value, limit) => (typeof value === 'string' ? value.replace(/\0/g, '').slice(0, limit) : '');

/** What goes along with a message: where the work should happen (a new tab, the tab the customer is on, or one they picked), the tabs involved (a grant name marks one the customer
 *  allowed Lumina to act in), the text they selected and the text of their page. Sizes are cut here the way the server cuts them. -> a plain object ({} for nothing). */
export function buildContext({ target, tabs = [], selection = '', page = '' } = {}) {
  const out = {};
  if (TARGETS.includes(target)) out.target = target;
  let room = 24000;      // the text of all the tabs together (the page the customer is on has its own, larger limit below)
  const list = (Array.isArray(tabs) ? tabs : []).slice(0, 8).map(t => {
    const text = cut(t?.text, Math.min(6000, room)); room -= text.length;
    return { title: cut(t?.title, 200), url: cut(t?.url, 2000), ...(typeof t?.grant === 'string' && /^[a-z0-9]{1,24}$/.test(t.grant) ? { grant: t.grant } : {}), ...(text.trim() ? { text } : {}) };
  });
  if (list.length) out.tabs = list;
  const sel = cut(selection, 4000), body = cut(page, 20000);
  if (sel.trim()) out.selection = sel;
  if (body.trim()) out.page = body;
  return out;
}

/** The endpoints the panel may reach, and what each accepts. Anything else is refused before it leaves the browser. */
export function buildCall(endpoint, input = {}) {
  if (endpoint === 'state' || endpoint === 'stop' || endpoint === 'history') return { method: endpoint === 'stop' ? 'POST' : 'GET', path: endpoint, query: '', body: undefined };
  if (endpoint === 'events') {
    const { request, after = 0, limit = 100 } = input;
    if (typeof request !== 'string' || !/^[a-f0-9]{32}$/.test(request) || !Number.isInteger(after) || after < 0 || !Number.isInteger(limit) || limit < 1 || limit > 100) return null;
    return { method: 'GET', path: 'events', query: `?request=${request}&after=${after}&limit=${limit}`, body: undefined };
  }
  if (endpoint === 'send') {
    const { message, key, mode, context } = input;
    if (typeof message !== 'string' || !message.trim() || message.length > MAX_MESSAGE || message.includes('\0') || typeof key !== 'string' || !KEY.test(key)) return null;
    if (mode !== undefined && !MODES.includes(mode)) return null;
    const body = { message, key, ...(mode ? { mode } : {}) };
    if (context !== undefined) { const clean = buildContext(context); if (Object.keys(clean).length) body.context = clean; }
    return { method: 'POST', path: 'send', query: '', body: JSON.stringify(body) };
  }
  return null;
}

export const STATE_LABEL = {
  waiting: 'Waiting to start', starting: 'Starting', running: 'Working', uncertain: 'Checking where it got to', completed: 'Done', done: 'Done', failed: 'Stopped', cancelled: 'Cancelled',
};

/** What the server's error codes mean to the customer. Unknown codes get the generic line; nothing from the network is shown as written. */
export const ERROR_TEXT = {
  ticket: 'Reconnecting…', device: 'This browser is not paired with Lumina any more. Pair it again in settings.', browser_off: 'Lumina is off in this browser, or another computer took over.',
  no_active_run: 'Nothing is running right now.', budget_denied: 'Your plan allowance cannot cover this message. Nothing was sent.', rate_limited: 'Too many messages in a short time. Try again in a minute.',
  request_conflict: 'That message could not be added. It may have just finished.', unavailable_now: 'Lumina is not reachable right now. Trying again…',
  invalid_request: 'That message could not be sent.', unavailable: 'The side chat is not available for this account.', no_ticket: 'Starting a new session…',
  bad_tab: 'That tab cannot be used.', tab_blocked: 'Lumina cannot work in that kind of page.',
};
export const errorText = code => ERROR_TEXT[code] || 'Something went wrong. Trying again…';

/** The assistant's readiness, as one line for the status area. */
export function cellLine(cell, live = false) {
  if (live) return '';
  if (cell === 'waking') return 'Waking your assistant. This takes about a minute the first time.';
  if (cell === 'asleep') return 'Your assistant is asleep. It wakes up as soon as you send something.';
  if (cell === 'ready') return 'Your assistant is awake.';
  return '';
}

/** The panel's status. link: what the service worker says ({ enabled, connected, paired, hasTicket }); state: what the server last said; error: the last code; sending: a send is under way. */
export function view({ link = {}, state = null, error = null, sending = false } = {}) {
  const none = { canSend: false, canStop: false };
  if (!link.paired) return { tone: 'off', headline: 'Connect this browser to Lumina', detail: 'Enter the pairing code from Lumina, Settings, Your browser.', needsPair: true, ...none };
  if (!link.enabled) return { tone: 'off', headline: 'Lumina is off in this browser', detail: 'Turn it on to chat and let Lumina work here.', canTurnOn: true, ...none };
  if (!link.connected) return { tone: 'wait', headline: 'Connecting to Lumina…', detail: '', ...none };
  if (error === 'device') return { tone: 'off', headline: 'This browser needs pairing again', detail: ERROR_TEXT.device, needsPair: true, ...none };
  if (error === 'browser_off') return { tone: 'off', headline: 'Lumina is not using this browser', detail: ERROR_TEXT.browser_off, canTurnOn: true, ...none };
  if (!link.hasTicket) return { tone: 'wait', headline: 'Starting a new session…', detail: '', ...none };
  if (!state) return { tone: 'wait', headline: 'Loading…', detail: '', canSend: !sending, canStop: false };
  const request = state.request;
  if (state.live) return { tone: 'on', headline: request?.paused ? 'Paused' : STATE_LABEL[request?.state] || 'Working', detail: '', canSend: !sending, canStop: true };
  const line = cellLine(state.cell);
  if (request && ['waiting', 'starting'].includes(request.state)) return { tone: 'wait', headline: state.cell === 'ready' ? 'Starting' : 'Waking your assistant…', detail: line, canSend: !sending, canStop: true };
  return { tone: request ? 'idle' : 'on', headline: request ? STATE_LABEL[request.state] || 'Finished' : 'Ready', detail: request ? '' : line, canSend: !sending, canStop: false };
}

/** One line for the activity trail, or null for events that are not worth a line (pictures and clicks of the person's own hands). */
export function stepLine(event) {
  if (!event || event.kind === 'screenshot' || event.kind === 'control') return null;
  const summary = event.payload?.summary;
  if (typeof summary === 'string' && summary.trim()) return summary.trim().slice(0, 300);
  return String(event.kind || 'step').replace(/_/g, ' ').slice(0, 60);
}

/** Add newly fetched events to the trail: ordered, no repeats, at most `cap` kept (the oldest drop first). */
export function mergeEvents(trail, incoming, cap = 200) {
  const seen = new Set(trail.map(e => e.sequence));
  const merged = [...trail, ...incoming.filter(e => Number.isInteger(e?.sequence) && !seen.has(e.sequence))].sort((a, b) => a.sequence - b.sequence);
  return merged.slice(-cap);
}

/** Milliseconds until the next look at the server: brisk while a task runs, calm when it does not, backing off after failures, slow when the panel is hidden. */
export function pollDelay({ live = false, failures = 0, hidden = false } = {}) {
  if (failures > 0) return Math.min(15000, 1000 * 2 ** Math.min(failures, 4));
  if (hidden) return 10000;
  return live ? 1500 : 4000;
}

/** One-press prompts, like the other assistants' extensions: what each needs from the page decides whether it can run, and the words that are sent. */
export const QUICK_ACTIONS = [
  { id: 'summarize', label: 'Summarize this page', needs: 'page', mode: 'auto', prompt: 'Summarize the page I am on in a few clear bullet points.' },
  { id: 'explain', label: 'Explain selection', needs: 'selection', mode: 'auto', prompt: 'Explain the text I selected in plain words.' },
  { id: 'keypoints', label: 'Key facts and dates', needs: 'page', mode: 'auto', prompt: 'List the key facts, numbers, names and dates on this page.' },
  { id: 'reply', label: 'Draft a reply', needs: 'selection', mode: 'auto', prompt: 'Draft a short, friendly reply to the text I selected.' },
  { id: 'translate', label: 'Translate selection', needs: 'selection', mode: 'auto', prompt: 'Translate the text I selected into English, and tell me the original language.' },
  { id: 'research', label: 'Research this', needs: 'page', mode: 'browse', prompt: 'Look into what this page is about using other sources, then tell me what you found and where.' },
];

/** Which quick actions can run now, given what the panel could read. */
export const availableActions = ({ hasPage = false, hasSelection = false } = {}) => QUICK_ACTIONS.filter(a => (a.needs === 'page' ? hasPage || hasSelection : a.needs === 'selection' ? hasSelection : true));

/** The saved prompts the customer keeps on this computer (a name and the words): at most 12, short. */
export function cleanPrompts(list) {
  if (!Array.isArray(list)) return [];
  return list.filter(p => p && typeof p.name === 'string' && typeof p.text === 'string' && p.name.trim() && p.text.trim()).slice(0, 12)
    .map(p => ({ name: p.name.trim().slice(0, 30), text: p.text.trim().slice(0, MAX_MESSAGE) }));
}

/** Pages Chrome never lets an extension act in (and ones Lumina will not work in): -> true when a tab with this address cannot be granted. */
export const restrictedUrl = url => {
  if (typeof url !== 'string' || !url) return true;
  try { const u = new URL(url); return !['http:', 'https:'].includes(u.protocol) || u.hostname === 'chromewebstore.google.com' || u.hostname === 'chrome.google.com'; } catch { return true; }
};
