// What the side panel shows and sends, as plain data in and plain data out, so it can be tested without a browser. Nothing here touches the page or the network.

/** The ticket the platform hands over (see platform/agentai_platform/panel/ticket.py): shaped like p1.<body>.<signature>, never looked inside. */
export const TICKET = /^p1\.[A-Za-z0-9_-]{1,500}\.[A-Za-z0-9_-]{1,100}$/;
const IDENT = /^[A-Za-z0-9_-]{1,64}$/;

/** A message from the platform on the device link -> { type: 'ticket', ticket, conversation, expiresAt } | { type: 'clear', conversation } | null (anything else is ignored). */
export function parsePush(panel, now = Date.now()) {
  if (!panel || typeof panel !== 'object' || typeof panel.conversation_id !== 'string' || !IDENT.test(panel.conversation_id)) return null;
  const { ticket, expires_in: life } = panel;
  if (typeof ticket !== 'string' || !TICKET.test(ticket) || !Number.isInteger(life) || life < 1 || life > 600) return null;
  return { type: 'ticket', ticket, conversation: panel.conversation_id, expiresAt: now + life * 1000 };
}

export const KEY = /^[A-Za-z0-9_-]{8,64}$/;
/** A fresh idempotency key for one send: pressing Send twice for the same text must not send twice, a new text must. */
export function newKey(random = globalThis.crypto) {
  const bytes = new Uint8Array(12); random.getRandomValues(bytes);
  return 'p' + [...bytes].map(b => b.toString(16).padStart(2, '0')).join('');
}

export const MAX_MESSAGE = 16000;
/** The endpoints the panel may reach, and the one thing each accepts. Anything else is refused before it leaves the browser. */
export function buildCall(endpoint, input = {}) {
  if (endpoint === 'state' || endpoint === 'stop') return { method: endpoint === 'state' ? 'GET' : 'POST', path: endpoint, query: '', body: undefined };
  if (endpoint === 'events') {
    const { request, after = 0, limit = 100 } = input;
    if (typeof request !== 'string' || !/^[a-f0-9]{32}$/.test(request) || !Number.isInteger(after) || after < 0 || !Number.isInteger(limit) || limit < 1 || limit > 100) return null;
    return { method: 'GET', path: 'events', query: `?request=${request}&after=${after}&limit=${limit}`, body: undefined };
  }
  if (endpoint === 'send') {
    const { message, key } = input;
    if (typeof message !== 'string' || !message.trim() || message.length > MAX_MESSAGE || message.includes('\0') || typeof key !== 'string' || !KEY.test(key)) return null;
    return { method: 'POST', path: 'send', query: '', body: JSON.stringify({ message, key }) };
  }
  return null;
}

export const STATE_LABEL = {
  waiting: 'Waiting to start', starting: 'Starting', running: 'Working', uncertain: 'Checking where it got to', completed: 'Done', done: 'Done', failed: 'Stopped', cancelled: 'Cancelled',
};

/** What the server's error codes mean to the customer. Unknown codes get the generic line; nothing from the network is shown as written. */
export const ERROR_TEXT = {
  ticket: 'Reconnecting…', browser_off: 'Lumina is off in this browser, or another computer took over.', no_active_run: 'Nothing is running right now. Open Lumina to start something.',
  budget_denied: 'Your plan allowance cannot cover this message. Nothing was sent.', rate_limited: 'Too many messages in a short time. Try again in a minute.',
  request_conflict: 'That message could not be added to the task. It may have just finished.', unavailable_now: 'Lumina is not reachable right now. Trying again…',
  invalid_request: 'That message could not be sent.', unavailable: 'The side chat is not available for this account.', no_ticket: 'Waiting for Lumina to start a task here…',
};
export const errorText = code => ERROR_TEXT[code] || 'Something went wrong. Trying again…';

/** The panel's status, from what the service worker says about the link ({ enabled, connected, hasTicket }), what the server last said (state, error) and whether a send is under way. */
export function view({ link = {}, state = null, error = null, sending = false } = {}) {
  const none = { canSend: false, canStop: false };
  if (!link.enabled) return { tone: 'off', headline: 'Lumina is off in this browser', detail: 'Turn it on from the toolbar button to use this chat.', ...none };
  if (!link.connected) return { tone: 'wait', headline: 'Reconnecting to Lumina…', detail: '', ...none };
  if (error === 'browser_off') return { tone: 'off', headline: 'Lumina is not using this browser', detail: ERROR_TEXT.browser_off, ...none };
  if (!state && !link.hasTicket) return { tone: 'wait', headline: 'Waiting for a task', detail: ERROR_TEXT.no_ticket, ...none };
  if (!state) return { tone: 'wait', headline: 'Loading…', detail: '', ...none };
  const request = state.request;
  if (state.live && link.hasTicket) return { tone: 'on', headline: request?.paused ? 'Paused' : STATE_LABEL[request?.state] || 'Working', detail: '', canSend: !sending, canStop: true };
  return { tone: 'idle', headline: request ? STATE_LABEL[request.state] || 'Finished' : 'Nothing is running', detail: 'Open Lumina to continue this chat.', ...none };
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
