// The runner's rules, for the extension. Same limits and the same address policy as ../../runner.mjs and platform/agentai_platform/browse/native_runner.py;
// test/extension-parity.test.mjs checks the verdicts against runner.mjs so the three cannot drift apart silently.
export const WIDTH = 1280, HEIGHT = 800;
export const MAX_ELEMENTS = 80, MAX_VALUE = 500, MAX_URL = 2048, MAX_PAGES = 3;
export const KEYS = new Set(['Enter', 'Tab', 'Escape']);
export const TAKEOVER_KEYS = new Set(['Backspace', 'Delete', 'ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Home', 'End', 'PageDown', 'PageUp']);
export const SELECTOR = 'a[href], button, input:not([type=hidden]), select, textarea, [role=button], [role=link], [role=checkbox], [role=radio], [role=tab], [onclick]';

/** An address (not a name) in a private, loopback, link-local or otherwise internal range. */
export function privateIp(h) {
  const m = h.match(/^(\d+)\.(\d+)\.(\d+)\.(\d+)$/);
  if (m) { const [a, b] = [+m[1], +m[2]]; return a === 10 || a === 127 || a === 0 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127); }
  if (h.includes(':')) {
    const v4 = h.toLowerCase().match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
    return v4 ? privateIp(v4[1]) : /^(fc|fd|fe80|::1|::)/i.test(h);
  }
  return false;
}

/** Public http/https only. On a customer's own computer "private" means their home network, so it is always refused; loopback is for tests. */
export function urlAllowed(raw, allowLoopback = false) {
  let u; try { u = new URL(raw); } catch { return false; }
  if (!['http:', 'https:'].includes(u.protocol)) return false;
  const h = u.hostname.toLowerCase().replace(/^\[|\]$/g, '');
  if (u.username || u.password) return false;
  const loop = h === 'localhost' || h === '127.0.0.1' || h === '::1';
  if (loop) return allowLoopback;
  if (h.endsWith('.local') || h.endsWith('.internal') || h.endsWith('.localhost')) return false;
  return !privateIp(h);
}

/** A point inside the window the pictures are judged against. */
export const pointOk = (x, y) => Number.isFinite(x) && Number.isFinite(y) && x >= 0 && y >= 0 && x <= WIDTH && y <= HEIGHT;
