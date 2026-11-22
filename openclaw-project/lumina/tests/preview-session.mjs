// Shared by the real-browser checks that run against tests/preview_mail.py: a browser signed in as the fixture's one synthetic customer, and a way to connect the
// stand-in accounts without clicking through the sign-in each time (the sign-in itself is checked by tests/mail-browser.mjs).
import { existsSync } from 'node:fs';
import { chromium } from '../../browse/node_modules/playwright-core/index.mjs';

export const BASE = process.env.MAIL_QA_URL || 'https://127.0.0.1:5183';
export const ZONE = 'America/Los_Angeles';

const customer = async page => {
  await page.goto(BASE + '/app/', { waitUntil: 'domcontentloaded' });
  const signed = await page.evaluate(async ([email, password]) => {
    const csrf = (await (await fetch('/v1/csrf', { credentials: 'same-origin' })).json()).csrf_token;
    return (await fetch('/auth/login', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ email, password }) })).status;
  }, ['mail-preview@example.invalid', 'Mail-Preview-2026!']);
  if (signed !== 200) throw new Error('the fixture customer could not sign in: ' + signed);
};
const sized = ({ width = 1440, height = 900, scale = 1 } = {}) => ({ viewport: { width, height }, deviceScaleFactor: scale, ignoreHTTPSErrors: true, timezoneId: ZONE, locale: 'en-US' });

/** -> { browser, context, page, again }. `scale` 2 with half the width and height is what a browser zoomed to 200% lays out. `again(size)` opens another window of
 *  another size with the same sign-in. Signing in each time runs into the sign-in limit (as it should), so with PREVIEW_STATE set to a file path the sign-in is kept
 *  there and used again by the next run, for as long as the fixture that gave it is still running. */
export async function session(size) {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const file = process.env.PREVIEW_STATE;
  let context = null, page = null;
  if (file && existsSync(file)) {
    context = await browser.newContext({ ...sized(size), storageState: file }); page = await context.newPage();
    await page.goto(BASE + '/app/', { waitUntil: 'domcontentloaded' });
    const still = await page.evaluate(() => fetch('/v1/hub', { credentials: 'same-origin' }).then(r => r.status)).catch(() => 0);
    if (still !== 200) { await context.close(); context = null; }
  }
  if (!context) {
    context = await browser.newContext(sized(size)); page = await context.newPage();
    await customer(page);
    if (file) await context.storageState({ path: file });
  }
  const again = async other => { const next = await browser.newContext({ ...sized(other), storageState: await context.storageState() }); return { context: next, page: await next.newPage() }; };
  return { browser, context, page, again };
}

/** Connect a stand-in account through the routes and let Lumina read all of it (mail and every calendar). -> the connection id. Does nothing when it is connected. */
export async function connect(page, provider, code) {
  return page.evaluate(async ([provider, code]) => {
    const call = async (path, body) => { const csrf = (await (await fetch('/v1/csrf', { credentials: 'same-origin' })).json()).csrf_token;
      const r = await fetch(path, body === undefined ? { credentials: 'same-origin' } : { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify(body) });
      return r.json().catch(() => null); };
    const have = (await call('/v1/hub')).accounts.find(a => a.provider === provider);
    if (have) return have.id;
    const link = await call('/v1/hub/link', { provider });
    const state = new URL(new URL(link.authorize_url).searchParams.get('real')).searchParams.get('state');
    const id = (await call('/v1/hub/link/finish', { state, code })).connection_id;
    const resources = (await call(`/v1/integrations/${id}/resources`)).resources;
    await call(`/v1/integrations/${id}/grants`, { grants: resources.filter(r => r.kind === 'mailbox' || r.kind === 'calendar') });
    await call('/v1/hub/refresh', { connection_id: id });
    return id;
  }, [provider, code]);
}
export const connectGoogle = page => connect(page, 'google', 'good-code');
export const connectMicrosoft = page => connect(page, 'microsoft', 'M.C5_BAY.2.U.fixture');

/** Wait until something is true in the page. (Playwright's own waitForFunction evaluates a string inside the page, which the app's content policy refuses.) */
export async function until(page, fn, arg, { timeout = 15000, polling = 250 } = {}) {
  const end = Date.now() + timeout;
  for (;;) { if (await page.evaluate(fn, arg).catch(() => false)) return; if (Date.now() > end) throw new Error('timed out waiting for: ' + fn.toString().replace(/\s+/g, ' ').slice(0, 160)); await page.waitForTimeout(polling); }
}
