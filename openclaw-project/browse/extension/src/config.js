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
