// The side panel's credential and its calls to the platform, kept in the service worker so the panel page never holds the ticket (and never the device token).
// A ticket comes from one of two places: the extension asks for a NEW session itself (open: it signs in with its own device token, and every open is a fresh conversation), or the
// platform hands one over on the device link while a task started in the web chat runs here (push, kept apart as `offered`: the panel may switch to it, never forced).
// It lives in memory only, lapses within a minute and a half of the last one, is renewed shortly before, and is dropped at once when the customer switches Lumina off, when the
// link goes, or when the server says it is no good.
import { parsePush, parseSession, buildCall } from './panel-model.js';

const RENEW_BEFORE_MS = 25_000;

export function createPanelLink({ base, isOn, token = async () => '', fetchFn = (...a) => fetch(...a), now = Date.now, onChange = () => {} }) {
  let held = null;         // { ticket, conversation, expiresAt, cell }
  let offered = null;      // the same shape, from the device link (a web-chat task is running here)
  let opening = null;

  const fresh = x => !!x && x.expiresAt > now();
  const drop = () => { if (held || offered) { held = null; offered = null; onChange(); } };

  async function post(path, headers, body) {
    const root = typeof base === 'function' ? await base() : base;
    let response;
    try {
      response = await fetchFn(`${root}/${path}`, {
        method: 'POST', credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer',
        headers: { ...headers, 'Content-Type': 'application/json' }, body: JSON.stringify(body ?? {}),
      });
    } catch { return { status: 0, data: { error: 'unavailable_now' } }; }
    let data = {};
    try { data = await response.json(); } catch { /* an error page: the status says enough */ }
    return { status: response.status, data: data && typeof data === 'object' ? data : {} };
  }

  /** Sign in with the device token and take a ticket: a NEW conversation, or (`conversation`) a fresh ticket for the one this panel already has. -> { status, data }. */
  async function session(conversation) {
    if (!isOn()) return { status: 0, data: { error: 'browser_off' } };
    const device = await token();
    if (!device) return { status: 0, data: { error: 'device' } };
    const out = await post('session', { Authorization: `Device ${device}` }, conversation ? { conversation } : {});
    if (out.status === 200) {
      const parsed = parseSession(out.data, now());
      if (!parsed) return { status: 0, data: { error: 'unavailable_now' } };
      const changed = !held || held.conversation !== parsed.conversation;
      held = parsed;
      if (changed) onChange();
    } else if (out.status === 401 && held) { held = null; onChange(); }
    return out;
  }

  return {
    /** A message from the platform on the device link. -> true when it was a panel message (handled here, never queued behind a browser command). */
    push(msg) {
      if (!msg || typeof msg !== 'object' || !('panel' in msg)) return false;
      const parsed = parsePush(msg.panel, now());
      if (parsed?.type === 'ticket') { const was = offered?.conversation; offered = { ...parsed, cell: 'unknown' }; if (was !== parsed.conversation) onChange(); }
      return true;
    },
    /** Start a new session (every open of the panel is one). Concurrent opens share one request. */
    open() { return (opening ??= session(null).finally(() => { opening = null; })); },
    /** The panel's session switches to the conversation the platform offered (a web-chat task running here). */
    useOffered() { if (!fresh(offered)) return false; held = offered; offered = null; onChange(); return true; },
    clear: drop,
    has: () => fresh(held),
    conversation: () => (fresh(held) ? held.conversation : null),
    offered: () => (fresh(offered) ? offered.conversation : null),
    /** One call for the panel page: { status, data } (status 0 = could not be made; data.error says why). */
    async call(endpoint, input) {
      if (!isOn()) return { status: 0, data: { error: 'browser_off' } };      // switched off: no call, even with a ticket still in hand
      const call = buildCall(endpoint, input);
      if (!call) return { status: 400, data: { error: 'invalid_request' } };
      if (held && held.expiresAt - now() < RENEW_BEFORE_MS && held.expiresAt > now() - 60_000) await session(held.conversation);      // renewed shortly before it lapses
      if (!fresh(held)) return { status: 0, data: { error: 'no_ticket' } };
      let response;
      try {
        const root = typeof base === 'function' ? await base() : base;
        response = await fetchFn(`${root}/${call.path}${call.query}`, {
          method: call.method, credentials: 'omit', cache: 'no-store', referrerPolicy: 'no-referrer',
          headers: { Authorization: `Panel ${held.ticket}`, ...(call.body ? { 'Content-Type': 'application/json' } : {}) }, body: call.body,
        });
      } catch { return { status: 0, data: { error: 'unavailable_now' } }; }
      let data = {};
      try { data = await response.json(); } catch { /* an error page: the status says enough */ }
      if (response.status === 401) { held = null; onChange(); }
      if (response.status === 200 && endpoint === 'state' && typeof data.cell === 'string') held.cell = data.cell;
      return { status: response.status, data: data && typeof data === 'object' ? data : {} };
    },
  };
}
