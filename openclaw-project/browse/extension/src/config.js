// What the extension will talk to, and what a pairing code looks like. Kept apart so the rules are small enough to read and test.

// Production: where the platform's device gateway listens (platform/deploy/caddy/Caddyfile.getlumina). Nothing a web page says can change this.
export const PROD_BRIDGE = 'wss://backend.getlumina.pro/v1/device';
// The only web origin allowed to hand the extension a pairing code (externally_connectable in manifest.json says the same).
export const LUMINA_ORIGIN = 'https://getlumina.pro';

const LOOPBACK = /^ws:\/\/(127\.0\.0\.1|localhost)(:\d{1,5})?\/[\w/-]*$/;
/** The address the extension may connect to: production, or this computer (development and tests). A stored override pointing anywhere else is ignored. */
export const bridgeAllowed = url => typeof url === 'string' && (url === PROD_BRIDGE || LOOPBACK.test(url));

/** A pairing code as typed or pasted (any case, with spaces or dashes) -> the 8 characters the platform issues, or '' when it cannot be one. */
export const normalisePairCode = raw => {
  const code = String(raw ?? '').toUpperCase().replace(/[^A-Z0-9]/g, '');
  return /^[A-HJKMNP-Z2-9]{8}$/.test(code) ? code : '';
};

// The platform's side-panel API (platform/accounts/panel.py), reached over HTTPS from the service worker with the panel ticket. Same rule as the bridge: production, or this computer.
export const PROD_PANEL_API = 'https://backend.getlumina.pro/v1/panel';
const LOOPBACK_HTTP = /^http:\/\/(127\.0\.0\.1|localhost)(:\d{1,5})?\/v1\/panel$/;
export const panelApiAllowed = url => typeof url === 'string' && (url === PROD_PANEL_API || LOOPBACK_HTTP.test(url));
