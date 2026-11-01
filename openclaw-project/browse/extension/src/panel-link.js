// The side panel's credential and its calls to the platform, kept in the service worker so the panel page never holds the ticket (and never the device token).
// The ticket arrives over the device link, only while a task of the customer's conversation is running here; it lives in memory only, lapses within a minute and a half
// of the last one, and is dropped at once when the customer switches Lumina off, when the link goes, or when the server says it is no good.
import { parsePush, buildCall } from './panel-model.js';

export function createPanelLink({ base, isOn, fetchFn = (...a) => fetch(...a), now = Date.now, onChange = () => {} }) {
  let held = null;      // { ticket, conversation, expiresAt }

  const fresh = () => !!held && held.expiresAt > now();
  const drop = () => { if (held) { held = null; onChange(); } };

  return {
    /** A message from the platform. -> true when it was a panel message (handled here, never queued behind a browser command). */
    push(msg) {
      if (!msg || typeof msg !== 'object' || !('panel' in msg)) return false;
      const parsed = parsePush(msg.panel, now());
      if (parsed?.type === 'ticket') { held = { ticket: parsed.ticket, conversation: parsed.conversation, expiresAt: parsed.expiresAt }; onChange(); }
      return true;
    },
    clear: drop,
    has: () => fresh(),
    /** One call for the panel page: { status, data } (status 0 = could not be made; data.error says why). */
    async call(endpoint, input) {
      if (!isOn()) return { status: 0, data: { error: 'browser_off' } };      // switched off: no call, even with a ticket still in hand
      const call = buildCall(endpoint, input);
      if (!call) return { status: 400, data: { error: 'invalid_request' } };
      if (!fresh()) return { status: 0, data: { error: 'no_ticket' } };
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
      if (response.status === 401) drop();
      return { status: response.status, data: data && typeof data === 'object' ? data : {} };
    },
  };
}
