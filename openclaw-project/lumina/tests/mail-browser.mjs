// Real-browser check of the mail experience on the real server code, with stand-in mail services (see tests/preview_mail.py). No real account, no network beyond localhost.
//   npm run build
//   ../platform/.venv/bin/python tests/preview_mail.py &            (https://127.0.0.1:5183, a fresh state each start: start it anew before each run of this)
//   node tests/mail-browser.mjs
// Covers: connecting each kind of account and every way a sign-in can connect nothing (each with its own sentence), how each kind of message is shown (plain, a web
// reply, a desktop reply, a newsletter, a receipt, pictures inside, right-to-left, one that tries what a message must not do), remote pictures held back and then
// shown, attachments, organizing with undo, writing, sending with Undo send, search, new mail arriving, an account whose access ended, and a phone-sized window.
// Screenshots go to MAIL_QA_OUTPUT (default /tmp/lumina-mail).
import { chromium } from '../../browse/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';

const BASE = process.env.MAIL_QA_URL || 'https://127.0.0.1:5183';
const out = process.env.MAIL_QA_OUTPUT || '/tmp/lumina-mail';
await mkdir(out, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, ignoreHTTPSErrors: true, acceptDownloads: true });
const page = await context.newPage();
const results = []; const refused = []; let doing = ''; const trace = [];
page.on('console', m => { const t = m.text(); if (/Content Security Policy|Refused to/i.test(t)) refused.push(`[${doing}] ${t.slice(0, 200)}`); });
if (process.env.MAIL_QA_TRACE) page.on('response', async r => { const u = new URL(r.url()); if (/organize|actions/.test(u.pathname)) trace.push(`[${doing}] ${r.status()} ${u.pathname} ${(await r.text().catch(e => 'NO BODY ' + e)).slice(0, 300)}`); });
page.on('pageerror', e => trace.push(`[${doing}] PAGE ERROR ${String(e).slice(0, 300)}`));
const unexpected = [];                                                          // answers of 400 and up that no step here asks for (a refused sign-in is asked for)
page.on('requestfailed', r => { const u = new URL(r.url()); if (u.pathname.startsWith('/v1/') && !/abort|cancel/i.test(r.failure()?.errorText ?? '')) unexpected.push(`FAILED ${r.method()} ${u.pathname} ${r.failure()?.errorText}`); });
const asked = new Map(); let askedNow = 0;                                     // how many requests each step made of the account server, by path (MAIL_QA_TRACE prints them)
// The account server allows a person 240 reads a minute (accounts/middleware.py), counted in whole minutes. A person never comes near it; this script, which loads the
// whole app nine times in its first seconds (once for each sign-in it tries), would. It keeps count and, before a step, waits for the next minute when this one is
// nearly used up: the limit stays on, as it is in production.
let minute = Math.floor(Date.now() / 60000), inMinute = 0;
page.on('request', r => { const u = new URL(r.url()); if (!u.pathname.startsWith('/v1/')) return; askedNow++; const k = `${doing} :: ${r.method()} ${u.pathname}`; asked.set(k, (asked.get(k) ?? 0) + 1);
  const now = Math.floor(Date.now() / 60000); if (now !== minute) { minute = now; inMinute = 0; } inMinute++; });
const pace = async () => { if (Math.floor(Date.now() / 60000) === minute && inMinute > 120) await new Promise(r => setTimeout(r, 60000 - (Date.now() % 60000) + 400)); };
const framed = [];                                                              // every address a frame inside the page went to
page.on('framenavigated', f => { if (f !== page.mainFrame()) framed.push(f.url()); });
const ASKED_FOR = new Set(['/v1/hub/link/finish', '/v1/app', '/v1/safety', '/v1/work/ticket']);     // a refused sign-in is what a step asks for; the others are asked before signing in and by other parts of the app that this fixture does not run
page.on('response', async r => { const u = new URL(r.url()); if (r.status() < 400 || !u.pathname.startsWith('/v1/') || ASKED_FOR.has(u.pathname)) return;
  unexpected.push(`${r.status()} ${r.request().method()} ${u.pathname} ${(await r.text().catch(() => '')).slice(0, 160)} <- ${(r.request().postData() || '').slice(0, 160)}`); });
const step = async (name, fn) => { await pace(); const t = Date.now(); doing = name.slice(0, 40); askedNow = 0; try { await fn(); results.push(`ok    ${name}  (${((Date.now() - t) / 1000).toFixed(1)}s, ${askedNow} requests)`); }
  catch (e) { results.push(`FAIL  ${name}\n        ${String(e.message || e).split('\n').slice(0, 6).join('\n        ')}`); await page.screenshot({ path: `${out}/FAIL-${name.replace(/[^a-z0-9]+/gi, '-').slice(0, 60)}.png` }).catch(() => {}); } };
const shot = name => page.screenshot({ path: `${out}/${name}.png` });
const state = async () => (await context.request.get(BASE + '/fake/state')).json();
const api = (path) => page.evaluate(async p => (await fetch(p, { credentials: 'same-origin' })).json(), path);
const row = subject => page.locator('.mail-row', { hasText: subject }).first();
const openThread = async subject => { await row(subject).locator('.mail-row-open').click(); await page.locator('.mail-subject', { hasText: subject.slice(0, 24) }).waitFor(); };
const frameReady = (n = 'last') => page.locator('iframe.hub-body-frame.ready')[n]().waitFor({ timeout: 15000 });
/** Read something out of the newest open message's own page (the frame), from the app's side. The app's content policy allows no `eval`, and the frame can run nothing:
 *  the function is put together here and handed over through the browser's own debugging channel, as every `evaluate` is. */
const inFrame = (fn, arg) => page.locator('iframe.hub-body-frame').last().evaluate((0, eval)(`(frame, arg) => (${fn.toString()})(frame.contentDocument, frame, arg)`), arg);
/** Wait until something is true in the page. (Playwright's own waitForFunction evaluates a string inside the page, which the app's content policy refuses.) */
const waitFor = async (fn, arg, options = {}) => { const end = Date.now() + (options.timeout ?? 15000);
  for (;;) { if (await page.evaluate(fn, arg).catch(() => false)) return; if (Date.now() > end) throw new Error('timed out waiting for: ' + fn.toString().replace(/\s+/g, ' ').slice(0, 160)); await page.waitForTimeout(options.polling ?? 200); } };
const mailbox = name => page.locator('.mail-nav .mail-nav-item').filter({ has: page.locator('.mail-nav-name', { hasText: new RegExp(`^${name}$`) }) });
const status = () => page.locator('.mail-status').first();
const overflow = () => page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);

// ---- signing in to Lumina ------------------------------------------------------------------------------------------------------------------------------
await page.goto(BASE + '/app/', { waitUntil: 'domcontentloaded' });
const signed = await page.evaluate(async ([email, password]) => {
  const csrf = (await (await fetch('/v1/csrf', { credentials: 'same-origin' })).json()).csrf_token;
  return (await fetch('/auth/login', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf }, body: JSON.stringify({ email, password }) })).status;
}, ['mail-preview@example.invalid', 'Mail-Preview-2026!']);
assert.equal(signed, 200, 'the synthetic customer signs in');
await page.goto(BASE + '/app/inbox', { waitUntil: 'domcontentloaded' });

const addAccount = async item => {
  const wanted = page.getByRole('menuitem', { name: item });
  for (let tries = 0; tries < 4 && !(await wanted.isVisible().catch(() => false)); tries++) {       // the menu is a toggle: press its button until the menu is open
    const first = page.getByRole('button', { name: 'Connect an account' });
    await (await first.count() ? first : page.getByRole('button', { name: 'Add an account' })).click();
    await wanted.waitFor({ timeout: 1500 }).catch(() => {});
  }
  await wanted.click();
  await page.waitForURL(/fake\/sign-in/);
};
const back = async way => { await page.click('#' + way); await page.waitForURL(/app\/inbox/); };
const banner = () => page.locator('.mail-banners .notice.warning').first();

await step('nothing connected: one sentence and one button, no standing notices', async () => {
  await page.getByText('Bring your mail into Lumina').waitFor();
  assert.equal(await page.getByText(/Read only for now/).count(), 0);
  await page.getByRole('button', { name: 'Connect an account' }).click();
  for (const item of ['Google', 'Personal: Outlook.com, Hotmail, Live', 'Work or school: Microsoft 365']) await page.getByRole('menuitem', { name: item }).waitFor();
  await shot('01-nothing-connected');
  await page.keyboard.press('Escape');
});

// ---- Microsoft: every way a sign-in can end ------------------------------------------------------------------------------------------------------------
const WAYS = [['decline', /You did not give access/, null], ['admin', /only an administrator allow apps like Lumina/, 'AADSTS65001'], ['admin-late', /only an administrator allow apps like Lumina/, 'AADSTS65001'],
  ['bad-secret', /refused Lumina itself, not your account/, 'AADSTS7000222'], ['no-mail', /without access to mail or calendars/, null], ['expired', /already used or took too long/, 'AADSTS70000']];
for (const [way, words, reference] of WAYS) await step(`Microsoft sign-in that connects nothing (${way}) says why`, async () => {
  await addAccount('Personal: Outlook.com, Hotmail, Live');
  assert.equal(await page.textContent('#at'), 'login.microsoftonline.com/consumers/oauth2/v2.0/authorize', 'a personal account goes to the personal sign-in');
  assert.match(await page.textContent('#scope'), /Mail\.Read Calendars\.Read openid email offline_access User\.Read$/, 'only reading is asked for');
  await back(way);
  await banner().waitFor();
  const said = await banner().textContent();
  assert.match(said, words); if (reference) assert.match(said, new RegExp(`Reference: ${reference}`));
  assert.doesNotMatch(said, /could not be connected\. Nothing was connected\. Please try again/);
  assert.equal((await api('/v1/hub')).accounts.length, 0, 'nothing was connected');
  assert.equal(await page.evaluate(() => location.hash + location.search.replace(/[?&]?(connect|ref)=[^&]*/g, '')), '', 'the sign-in values are out of the address');
  if (way === 'bad-secret') await shot('02-sign-in-refused-says-why');
});

await step('Microsoft work account: its own sign-in, a return as long as a real one, connected, folders offered', async () => {
  await addAccount('Work or school: Microsoft 365');
  assert.equal(await page.textContent('#at'), 'login.microsoftonline.com/organizations/oauth2/v2.0/authorize');
  await back('work');                                                           // a code of 2,400 characters
  const choose = page.getByRole('dialog', { name: /Choose what Lumina may read in dana@outlook\.test/ });
  await choose.waitFor({ timeout: 15000 });
  await choose.getByText('Only these folders').waitFor();
  assert.equal(await choose.getByRole('radio', { name: 'No mail' }).isChecked(), true, 'nothing is chosen for the customer');
  await shot('03-microsoft-connected-choose');
  await choose.getByRole('radio', { name: 'All mail' }).check();
  await choose.getByRole('button', { name: 'Let Lumina read these' }).click();
  await row('Lease renewal: the signed copy').waitFor({ timeout: 30000 });
  const account = (await api('/v1/hub')).accounts[0];
  assert.deepEqual([account.provider_label, account.identity, account.state], ['Microsoft', 'dana@outlook.test', 'working']);
});

await step('Microsoft mail is read: a message in the theme, the picture in its signature, a download, a folded quote', async () => {
  await openThread('Lease renewal: the signed copy'); await frameReady();
  const seen = await inFrame((doc) => { const cs = getComputedStyle(doc.body); const img = doc.querySelector('img'); return { font: cs.fontFamily, bg: getComputedStyle(doc.documentElement).backgroundColor, scheme: getComputedStyle(doc.documentElement).colorScheme,
    text: getComputedStyle(doc.querySelector('div')).color, picture: img ? [img.complete, img.naturalWidth, new URL(img.src).pathname] : null, sheets: doc.styleSheets.length }; });
  assert.doesNotMatch(seen.font, /Times/); assert.equal(seen.bg, 'rgba(0, 0, 0, 0)'); assert.equal(seen.scheme, 'dark');
  const ink = await page.evaluate(() => { const probe = document.createElement('span'); probe.style.color = 'var(--text-primary)'; document.body.append(probe); const c = getComputedStyle(probe).color; probe.remove(); return c; });
  assert.equal(seen.text, ink, 'the sender\'s black text takes the theme\'s text colour');
  assert.deepEqual(seen.picture, [true, 48, '/v1/hub/mail/file'], 'the picture carried in the message is shown from Lumina');
  const download = page.waitForEvent('download');
  await page.getByRole('link', { name: 'Download Lease renewal (signed).pdf' }).click();
  assert.equal((await download).suggestedFilename(), 'Lease renewal (signed).pdf');
  assert.equal(await page.locator('.mail-files .mail-file').count(), 1, 'the signature picture is not listed as a file');
  assert.equal(await page.getByRole('toolbar', { name: 'This conversation' }).getByRole('button').count(), 0, 'changes in this account are not offered until proven: nothing is drawn disabled');
  await shot('04-microsoft-message');
  await openThread('Re: Saturday hike'); await frameReady();
  const quote = await inFrame(doc => { const d = doc.querySelector('details.lumina-quote'); return d ? [d.open, d.textContent.includes('Who is in for Saturday')] : null; });
  assert.deepEqual(quote, [false, true]);
});

// ---- Google ----------------------------------------------------------------------------------------------------------------------------------------------
await step('Google: declined says so; then connected beside the first account, one list from both', async () => {
  await addAccount('Google'); await back('decline');
  assert.match(await banner().textContent(), /You did not give access/);
  await addAccount('Google');
  assert.match(await page.textContent('#scope'), /gmail\.readonly .*calendar\.readonly openid email$/);
  await back('continue');
  const choose = page.getByRole('dialog', { name: /Choose what Lumina may read in dana\.reyes@gmail\.test/ });
  await choose.getByRole('radio', { name: 'All mail' }).check();
  await choose.getByRole('button', { name: 'Let Lumina read these' }).click();
  await row('The autumn edit is here').waitFor({ timeout: 40000 });
  await waitFor(async () => { const r = await (await fetch('/v1/hub', { credentials: 'same-origin' })).json(); return r.accounts.length === 2 && r.accounts.every(a => a.mail && a.mail.filled); }, null, { timeout: 60000, polling: 1500 });
  await page.reload({ waitUntil: 'domcontentloaded' }); await row('The autumn edit is here').waitFor();
  await row('Lease renewal: the signed copy').waitFor();
  await page.locator('.mail-account-row').nth(1).waitFor();
  assert.equal(await page.locator('.mail-account-row').count(), 2);
  assert.equal(await page.getByText(/Read only for now/).count(), 0);
  await shot('05-unified-inbox');
});

await step('one account at a time, and all of them again', async () => {
  await page.getByRole('button', { name: /dana@outlook\.test/ }).click();
  await waitFor(() => !document.body.textContent.includes('The autumn edit is here'));
  assert.equal(await row('Lease renewal').count(), 1);
  await page.getByRole('button', { name: 'All accounts' }).click();
  await row('The autumn edit is here').waitFor();
});

// ---- how each kind of message is shown ---------------------------------------------------------------------------------------------------------------------
await step('a newsletter is shown as sent, on a light page of its own, with its remote pictures held back', async () => {
  const before = (await state()).pictures.length;
  await openThread('The autumn edit is here'); await frameReady();
  const seen = await inFrame((doc, frame) => { const h1 = doc.querySelector('h1'); const cta = doc.querySelector('.btn a'); return { designed: frame.classList.contains('designed'), page: getComputedStyle(doc.documentElement).backgroundColor,
    heading: getComputedStyle(h1).fontFamily, headingSize: getComputedStyle(h1).fontSize, button: getComputedStyle(cta).backgroundColor, body: getComputedStyle(doc.body).fontFamily,
    pictures: doc.images.length, alt: doc.querySelectorAll('.lumina-alt').length, wide: doc.documentElement.scrollWidth <= frame.clientWidth + 1, height: frame.clientHeight }; });
  assert.equal(seen.designed, true); assert.equal(seen.page, 'rgb(255, 255, 255)'); assert.match(seen.heading, /Georgia/); assert.ok(['26px', '22px'].includes(seen.headingSize), 'the heading is the size the sender set (22px where their own narrow-screen rule applies)');
  assert.equal(seen.button, 'rgb(37, 99, 235)', 'the sender\'s own style sheet is applied'); assert.doesNotMatch(seen.body, /Times/);
  assert.equal(seen.pictures, 0); assert.ok(seen.alt >= 3, 'what each picture was is still said'); assert.equal(seen.wide, true); assert.ok(seen.height > 500, 'the frame is as tall as the message');
  assert.match(await page.locator('.mail-pictures').textContent(), /5 pictures are hidden, so the sender cannot tell that you opened this/);
  assert.equal((await state()).pictures.length, before, 'opening the message asked the sender\'s server for nothing');
  await shot('06-newsletter-pictures-held-back');
  await page.getByRole('button', { name: 'Show pictures' }).click();
  await waitFor(() => { const f = [...document.querySelectorAll('iframe.hub-body-frame')].pop(); return f?.contentDocument?.images.length >= 4 && [...f.contentDocument.images].every(i => i.complete && i.naturalWidth > 0); }, null, { timeout: 15000 });
  const asked = (await state()).pictures.slice(before);
  assert.ok(asked.length >= 4); assert.ok(asked.every(p => p[2] === ''), 'no address of Lumina is given to the sender\'s server with a picture');
  assert.ok(!asked.some(p => p[1].includes('-import')), 'what a style sheet tries to load from elsewhere is never loaded');
  assert.equal(await page.locator('.mail-pictures').count(), 0);
  await page.waitForTimeout(400); await shot('07-newsletter-pictures-shown');
});

await step('a reply from a desktop mail program: in the theme, its colours readable, the earlier messages folded, its files offered', async () => {
  await openThread('Quarterly numbers for review'); await frameReady();
  const seen = await inFrame((doc, frame) => { const d = doc.querySelector('details.lumina-quote'); const red = [...doc.querySelectorAll('span')].find(s => s.textContent.includes('Travel is 18%'));
    const lum = c => { const [r, g, b] = c.match(/\d+/g).map(Number).map(v => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
    return { designed: frame.classList.contains('designed'), bg: getComputedStyle(doc.documentElement).backgroundColor, folded: d && !d.open, hidden: d && d.textContent.includes('board pack'), para: getComputedStyle(doc.querySelector('p.MsoNormal')).fontFamily,
      redLum: lum(getComputedStyle(red).color), textLum: lum(getComputedStyle(doc.querySelector('p.MsoNormal')).color), before: frame.clientHeight }; });
  assert.equal(seen.designed, false); assert.equal(seen.bg, 'rgba(0, 0, 0, 0)'); assert.equal(seen.folded, true); assert.equal(seen.hidden, true);
  assert.match(seen.para, /Calibri/, 'the sender\'s own type is kept'); assert.ok(seen.textLum > 0.7, 'black body text is the theme\'s text colour'); assert.ok(seen.redLum > 0.15, 'dark red is lifted far enough to read');
  await page.frameLocator('iframe.hub-body-frame >> nth=-1').locator('summary').click();
  await waitFor(h => [...document.querySelectorAll('iframe.hub-body-frame')].pop().clientHeight > h + 40, seen.before);
  assert.equal(await page.locator('.mail-files .mail-file').count(), 2);
  assert.equal(await page.locator('.mail-message').count(), 2); assert.equal(await page.locator('iframe.hub-body-frame').count(), 1, 'only the newest message is open');
  await shot('08-desktop-reply-quote-open');
});

await step('pictures inside a message are shown, a picture among the files opens here, a file downloads', async () => {
  await openThread('Chart from this morning'); await frameReady();
  await waitFor(() => { const f = [...document.querySelectorAll('iframe.hub-body-frame')].pop(); const i = f.contentDocument.querySelector('img'); return i && i.complete && i.naturalWidth === 420; });
  assert.deepEqual(await page.locator('.mail-file-text b').allTextContents(), ['Growth deck.pdf', 'Screenshot 2026-11-21.png']);
  await page.getByTitle('Show Screenshot 2026-11-21.png').click();
  const shown = page.getByRole('dialog', { name: 'Screenshot 2026-11-21.png' });
  await shown.locator('img').waitFor(); await waitFor(() => { const i = document.querySelector('.mail-preview > img'); return i.complete && i.naturalWidth === 360; });
  await shot('09-picture-opened');
  await page.keyboard.press('Escape'); await shown.waitFor({ state: 'detached' });
  await page.locator('.mail-subject', { hasText: 'Chart from this morning' }).waitFor();
  const file = await page.evaluate(async href => { const r = await fetch(href, { credentials: 'same-origin' }); return [r.status, r.headers.get('content-type'), r.headers.get('content-disposition'), r.headers.get('content-security-policy'), (await r.text()).slice(0, 8)]; },
    await page.getByRole('link', { name: 'Download Growth deck.pdf' }).getAttribute('href'));
  assert.deepEqual([file[0], file[1], file[3], file[4]], [200, 'application/octet-stream', "default-src 'none'; sandbox", '%PDF-1.4']); assert.match(file[2], /^attachment; filename="Growth deck\.pdf"/);
});

await step('a message that tries everything a message must not do can do none of it', async () => {
  const before = (await state()).pictures.length; const title = await page.title();
  await openThread('Action required: verify your account'); await frameReady(); await page.waitForTimeout(800);
  const seen = await inFrame(doc => ({ bad: doc.querySelectorAll('script, iframe, form, input, button, object, embed, svg, meta[http-equiv], link, base').length, handlers: [...doc.querySelectorAll('*')].some(e => [...e.attributes].some(a => a.name.startsWith('on'))),
    js: doc.querySelector('#js-link')?.getAttribute('href') ?? null, real: [doc.querySelector('#real-link')?.target, doc.querySelector('#real-link')?.rel], fixed: [...doc.querySelectorAll('*')].some(e => getComputedStyle(e).position === 'fixed'), title: doc.title }));
  assert.deepEqual([seen.bad, seen.handlers, seen.js, seen.fixed], [0, false, null, false]); assert.deepEqual(seen.real, ['_blank', 'noopener noreferrer nofollow']);
  assert.equal(await page.title(), title); assert.doesNotMatch(seen.title, /RAN/);
  assert.equal((await state()).pictures.length, before, 'nothing was asked of the sender\'s server: no script, frame, form, style sheet, font, redirect or picture');
  const policy = await page.evaluate(async src => { const r = await fetch(src, { credentials: 'same-origin' }); return [r.headers.get('content-security-policy'), r.headers.get('x-frame-options'), r.headers.get('referrer-policy')]; },
    await page.locator('iframe.hub-body-frame').last().getAttribute('src'));
  assert.match(policy[0], /default-src 'none'.*img-src 'self' data:;.*frame-ancestors 'self'.*sandbox allow-same-origin allow-popups/); assert.doesNotMatch(policy[0], /script|https:/); assert.deepEqual(policy.slice(1), ['SAMEORIGIN', 'no-referrer']);
  await page.getByRole('button', { name: 'Show pictures' }).click();
  await waitFor(n => fetch('/fake/state').then(r => r.json()).then(s => s.pictures.length > n), before, { timeout: 10000 });
  await page.waitForTimeout(700);
  const asked = (await state()).pictures.slice(before).map(p => p[1]);
  assert.ok(asked.every(q => /-img$|-css$|-sheet$/.test(q)), 'even with pictures on, only pictures are loaded: ' + asked.join(' '));
  assert.equal(await page.title(), title);
  await shot('10-hostile-message-inert');
});

await step('the sender\'s colours and type are kept where they read, right-to-left text runs right to left', async () => {
  await openThread('Colours and a table'); await frameReady();
  const seen = await inFrame(doc => { const spans = [...doc.querySelectorAll('span, font')]; const of = text => getComputedStyle(spans.find(s => s.textContent.startsWith(text))); const rgb = c => c.match(/\d+/g).slice(0, 3).map(Number);
    return { serif: of('A serif heading').fontFamily, green: rgb(of('Green').color), navy: rgb(of('Navy').color), table: getComputedStyle(doc.querySelector('table')).borderCollapse, link: getComputedStyle(doc.querySelector('a')).color }; });
  assert.match(seen.serif, /Georgia/); assert.ok(seen.green[1] > seen.green[0] && seen.green[1] > seen.green[2], 'green stays green'); assert.ok(seen.navy[2] > 200, 'navy is lifted to a blue that reads on a dark page'); assert.equal(seen.table, 'collapse');
  await shot('11-colours-in-the-theme');
  await openThread('جلسهٔ فردا'); await frameReady();
  assert.equal(await inFrame(doc => getComputedStyle(doc.querySelector('div')).direction), 'rtl');
  assert.equal(await page.locator('.mail-subject').getAttribute('dir'), 'auto');
  await shot('12-right-to-left');
});

await step('a long conversation: the newest open, the earlier ones one line each and opened on demand', async () => {
  await page.getByLabel('Search mail').fill('Field notes'); await page.keyboard.press('Enter');
  await openThread('Field notes: the survey'); await frameReady();
  assert.equal(await page.locator('.mail-message').count(), 8); assert.equal(await page.locator('.mail-message.open').count(), 1);
  await page.locator('.mail-message').nth(2).locator('.mail-message-toggle').click();
  await waitFor(() => document.querySelectorAll('iframe.hub-body-frame.ready').length === 2);
  await shot('13-long-thread');
  await page.getByRole('button', { name: 'Clear the search' }).click(); await row('The autumn edit is here').waitFor();
});

// ---- organizing --------------------------------------------------------------------------------------------------------------------------------------------
const labelsOf = async (subject, label = 'all') => { const s = await state(); const t = await api(`/v1/hub/mail/threads?label=${label}&q=` + encodeURIComponent(subject)); return s.google_labels[t.threads[0]?.id] ?? null; };
await step('archive with a key moves on to the next conversation, reaches the mailbox, and Undo puts it back', async () => {
  await openThread('Receipt for order #48213');
  const next = await page.locator('.mail-row.current + *').count();
  await page.keyboard.press('e');
  await status().getByText('Archived.').waitFor();
  await waitFor(() => !document.querySelector('.mail-subject')?.textContent.includes('Receipt for order'));
  assert.equal(await row('Receipt for order #48213').count(), 0); assert.ok(next >= 0);
  await waitFor(() => fetch('/fake/state').then(r => r.json()).then(s => s.modified.length > 0));
  assert.ok(!(await labelsOf('Receipt for order #48213')).includes('INBOX'), 'archived at the mail service');
  await status().getByRole('button', { name: 'Undo' }).click();
  await status().getByText('Undone.').waitFor();
  await row('Receipt for order #48213').waitFor({ timeout: 15000 });
  assert.ok((await labelsOf('Receipt for order #48213')).includes('INBOX'));
});

await step('star, mark read and unread, the bin and back: each shows at once and reaches the mailbox', async () => {
  await openThread('Colours and a table');
  await page.getByRole('toolbar', { name: 'This conversation' }).getByRole('button', { name: 'Star' }).click();
  await page.getByRole('toolbar', { name: 'This conversation' }).getByRole('button', { name: 'Remove the star' }).waitFor();
  await waitFor(() => fetch('/v1/hub/mail/threads?label=starred&q=Colours', { credentials: 'same-origin' }).then(r => r.json()).then(r => r.threads.length === 1), null, { timeout: 15000, polling: 800 });
  assert.ok((await labelsOf('Colours and a table')).includes('STARRED'));
  const unread = row('Lunch on Thursday?');
  await unread.hover(); await unread.getByRole('button', { name: 'Mark as read' }).click();
  await waitFor(() => !document.querySelector('.mail-row.unread .mail-row-subject')?.textContent.includes('Lunch on Thursday') );
  await waitFor(() => fetch('/fake/state').then(r => r.json()).then(s => s.modified.length >= 3), null, { timeout: 10000 });
  await row('Colours and a table').hover(); await row('Colours and a table').getByRole('button', { name: 'Move to the bin' }).click();
  await status().getByText('Moved to the bin.').waitFor();
  assert.equal(await row('Colours and a table').count(), 0);
  await mailbox('Bin').click();
  await row('Colours and a table').waitFor({ timeout: 15000 });
  assert.ok((await labelsOf('Colours and a table', 'trash')).includes('TRASH'));
  await mailbox('Inbox').click(); await row('The autumn edit is here').waitFor();
});

await step('several at once: select, archive, undo; an account that may not change mail offers no change', async () => {
  await page.getByLabel('Search mail').fill('2031'); await page.keyboard.press('Enter');          // two conversations, one of each sender, whatever is on screen
  await row('Invoice 2031 is ready (4)').waitFor(); await row('The autumn edit is here').waitFor({ state: 'detached' });
  for (const subject of ['Invoice 2031 is ready (2)', 'Invoice 2031 is ready (3)']) { const r = row(subject); await r.hover(); await r.getByRole('checkbox').click(); }
  const bar = page.getByRole('toolbar', { name: 'Selected conversations' });
  assert.match(await bar.textContent(), /2 selected/); await shot('14-selected');
  await bar.getByRole('button', { name: 'Archive' }).click();
  await status().getByText('Archived 2 conversations.').waitFor();
  await page.getByRole('button', { name: 'Clear the search' }).click(); await row('The autumn edit is here').waitFor();
  await waitFor(() => fetch('/v1/hub/mail/threads?label=inbox&q=2031', { credentials: 'same-origin' }).then(r => r.json()).then(r => r.threads.length === 2), null, { timeout: 15000, polling: 800 });
  await status().getByRole('button', { name: 'Undo' }).click(); await status().getByText('Undone.').waitFor();
  await waitFor(() => fetch('/v1/hub/mail/threads?label=inbox&q=2031', { credentials: 'same-origin' }).then(r => r.json()).then(r => r.threads.length === 4), null, { timeout: 15000, polling: 800 });
  const theirs = row('Lease renewal: the signed copy'); await theirs.hover();
  assert.equal(await theirs.getByRole('group', { name: /Quick actions/ }).count(), 0);
});

// ---- writing and sending -----------------------------------------------------------------------------------------------------------------------------------
await step('a new message: from either account, people suggested from the customer\'s own mail, saved by itself, listed under Drafts', async () => {
  await page.keyboard.press('Escape'); await page.locator('body').click({ position: { x: 5, y: 5 } }).catch(() => {});
  await page.getByRole('button', { name: 'Compose' }).click();
  const editor = page.getByRole('region', { name: 'New message' });
  assert.deepEqual(await editor.getByLabel('From').locator('option').allTextContents(), ['dana@outlook.test', 'dana.reyes@gmail.test']);
  await editor.getByLabel('From').selectOption({ label: 'dana.reyes@gmail.test' });
  await editor.getByLabel('To', { exact: true }).pressSequentially('ada', { delay: 30 });
  await editor.getByRole('listbox', { name: 'People for To' }).getByText('Ada Park').waitFor();
  await shot('15-compose-suggestions');
  await page.keyboard.press('Enter');
  assert.equal(await editor.getByLabel('To', { exact: true }).inputValue(), 'ada.park@example.com, ');
  await editor.getByLabel('Subject').fill('Table for Thursday');
  await editor.getByLabel('Message').fill('Booked for noon, by the window.\n\nDana');
  await editor.getByText('Saved in Lumina').waitFor({ timeout: 8000 });
  const drafts = (await api('/v1/hub/drafts')).drafts;
  assert.deepEqual([drafts.length, drafts[0].subject, drafts[0].to], [1, 'Table for Thursday', ['ada.park@example.com']]);
  assert.equal((await state()).sent.length, 0, 'writing and saving sent nothing');
  await shot('16-compose-saved');
});

await step('Send: what to know first, Undo send stops it, sending again goes out once and is in Sent', async () => {
  const editor = page.getByRole('region', { name: 'New message' });
  await editor.getByRole('button', { name: 'Send' }).click();
  const sending = editor.locator('.mail-sending');
  const first = editor.getByRole('alertdialog', { name: 'Before you send' });
  await Promise.race([first.waitFor(), sending.waitFor()]).catch(() => {});
  if (await first.count()) { await shot('17-before-you-send'); await first.getByRole('button', { name: 'Send anyway' }).click(); }
  await sending.waitFor(); assert.match(await sending.textContent(), /Sending from dana\.reyes@gmail\.test in \d+ s/);
  await editor.getByRole('button', { name: 'Undo send' }).click();
  await editor.getByText('Not sent. The draft is still here.').waitFor();
  await page.waitForTimeout(1500); assert.equal((await state()).sent.length, 0, 'stopped in time: nothing went out');
  await editor.getByRole('button', { name: 'Send' }).click();
  await Promise.race([first.waitFor({ timeout: 5000 }), sending.waitFor({ timeout: 5000 })]).catch(() => {});
  if (await first.count()) await first.getByRole('button', { name: 'Send anyway' }).click();
  await waitFor(() => fetch('/fake/state').then(r => r.json()).then(s => s.sent.length === 1), null, { timeout: 40000, polling: 1000 });
  const sent = (await state()).sent[0];
  assert.equal(sent.headers.To, 'ada.park@example.com'); assert.equal(sent.headers.Subject, 'Table for Thursday'); assert.match(sent.headers.From, /dana\.reyes@gmail\.test/); assert.match(sent.body, /Booked for noon/);
  await status().getByText('Sent.').waitFor({ timeout: 20000 });
  await page.waitForTimeout(2500); assert.equal((await state()).sent.length, 1, 'once, not twice');
  assert.equal((await api('/v1/hub/drafts')).drafts.length, 0, 'it is no longer a draft');
  await mailbox('Sent').click();
  await row('Table for Thursday').waitFor({ timeout: 20000 });
  await mailbox('Inbox').click(); await row('The autumn edit is here').waitFor();
});

await step('a reply carries what it answers, in its conversation, and goes to who wrote last', async () => {
  await openThread('Lunch on Thursday?'); await frameReady();
  await page.keyboard.press('r');
  const editor = page.getByRole('region', { name: 'Your reply' });
  assert.equal(await editor.getByLabel('To', { exact: true }).inputValue(), 'ada.park@example.com'); assert.equal(await editor.getByLabel('Subject').inputValue(), 'Re: Lunch on Thursday?');
  assert.match(await editor.getByLabel('Message').inputValue(), /\n\nOn .*Ada Park <ada\.park@example\.com> wrote:\n> Perfect, noon it is\./);
  await editor.getByLabel('Message').press('Control+Home').catch(() => {});
  await editor.getByLabel('Message').evaluate(el => { el.setSelectionRange(0, 0); });
  await editor.getByLabel('Message').pressSequentially('See you there.', { delay: 5 });
  await shot('18-reply-in-thread');
  await editor.getByRole('button', { name: 'Send' }).click();
  const first = editor.getByRole('alertdialog', { name: 'Before you send' });
  await Promise.race([first.waitFor({ timeout: 4000 }), editor.locator('.mail-sending').waitFor({ timeout: 4000 })]).catch(() => {});
  if (await first.count()) await first.getByRole('button', { name: 'Send anyway' }).click();
  await waitFor(() => fetch('/fake/state').then(r => r.json()).then(s => s.sent.length === 2), null, { timeout: 40000, polling: 1000 });
  const sent = (await state()).sent[1];
  assert.equal(sent.headers.Subject, 'Re: Lunch on Thursday?'); assert.match(sent.body, /^See you there\./); assert.ok(sent.thread, 'sent into the conversation it answers'); assert.ok(sent.headers['In-Reply-To'], 'and marked as an answer');
});

// ---- finding, staying current, an account whose access ended ---------------------------------------------------------------------------------------------------
await step('search finds mail in either account; the filters narrow the list', async () => {
  await page.keyboard.press('Escape');
  await page.getByLabel('Search mail').fill('renewal'); await page.keyboard.press('Enter');
  await row('Lease renewal: the signed copy').waitFor(); await row('Parking permit renewal').waitFor();
  await row('The autumn edit is here').waitFor({ state: 'detached' });
  await page.getByRole('button', { name: 'Clear the search' }).click(); await row('The autumn edit is here').waitFor();
  await page.getByRole('button', { name: 'Unread', exact: true }).click();
  await waitFor(() => document.querySelectorAll('.mail-row').length > 0 && [...document.querySelectorAll('.mail-row')].every(r => r.classList.contains('unread')));
  await page.getByRole('button', { name: 'Unread', exact: true }).click();
  await page.getByRole('button', { name: 'Attachments' }).click(); await row('Chart from this morning').waitFor();
  await row('The autumn edit is here').waitFor({ state: 'detached' });
  await page.getByRole('button', { name: 'Attachments' }).click(); await row('The autumn edit is here').waitFor();
});

await step('new mail arrives by itself, at the top, without a reload', async () => {
  await context.request.get(BASE + '/fake/arrive');
  await row('Just arrived: can you call me?').waitFor({ timeout: 40000 });
  assert.ok((await page.locator('.mail-row').evaluateAll(rows => rows.slice(0, 4).map(r => r.textContent))).some(t => t.includes('Just arrived')), 'among the newest');
});

await step('new mail while reading far down the list: it joins the top by itself, nothing is asked, the reader stays where they were', async () => {
  const list = page.locator('.mail-list');
  const total = () => list.locator('.vlist-rows > li').first().getAttribute('aria-setsize').then(Number);
  await list.evaluate(el => { el.scrollTop = el.scrollHeight; });
  await waitFor(() => Number(document.querySelector('.mail-list .vlist-rows > li')?.getAttribute('aria-setsize')) > 50, null, { timeout: 15000 });      // a further page was read
  await list.evaluate(el => { el.scrollTop = 30 * 84; }); await page.waitForTimeout(400);
  const before = await total();
  const reading = await list.evaluate(el => { const top = el.getBoundingClientRect().top; const row = [...el.querySelectorAll('.mail-row')].find(r => r.getBoundingClientRect().top >= top);
    return { subject: row.querySelector('.mail-row-subject').textContent, at: Math.round(row.getBoundingClientRect().top - top) }; });
  await context.request.get(BASE + '/fake/arrive');
  await waitFor(n => Number(document.querySelector('.mail-list .vlist-rows > li')?.getAttribute('aria-setsize')) === n + 1, before, { timeout: 45000, polling: 500 });
  assert.equal(await page.getByText(/There is new mail/).count(), 0); assert.equal(await page.getByRole('button', { name: 'Show it' }).count(), 0);
  const after = await list.evaluate((el, subject) => { const top = el.getBoundingClientRect().top; const row = [...el.querySelectorAll('.mail-row')].find(r => r.querySelector('.mail-row-subject').textContent === subject);
    return row ? Math.round(row.getBoundingClientRect().top - top) : null; }, reading.subject);
  assert.equal(after, reading.at, 'the row being read is where it was');
  assert.ok(await total() > 50, 'what was loaded further down is still there');
  await list.evaluate(el => { el.scrollTop = 0; });
  await waitFor(() => [...document.querySelectorAll('.mail-row')].slice(0, 4).filter(r => r.textContent.includes('Just arrived')).length >= 1);
  await shot('19b-new-mail-on-top');
});

await step('an account whose access ended says so, keeps its mail, and is connected again in place with what it was allowed', async () => {
  const beforeId = (await api('/v1/hub')).accounts.find(a => a.provider === 'google').id;
  await context.request.get(BASE + '/fake/expire?provider=google');
  const lost = page.locator('.mail-banners .notice', { hasText: 'dana.reyes@gmail.test is no longer connected' });
  await lost.waitFor({ timeout: 30000 });
  await row('The autumn edit is here').waitFor();
  await shot('19-access-ended');
  await lost.getByRole('button', { name: 'Reconnect' }).click();
  await page.waitForURL(/fake\/sign-in/);
  assert.equal(await page.textContent('#hint'), 'dana.reyes@gmail.test'); assert.match(await page.textContent('#scope'), /gmail\.send/, 'what it held is asked for again');
  await back('continue');
  await waitFor(() => fetch('/v1/hub', { credentials: 'same-origin' }).then(r => r.json()).then(r => r.accounts.every(a => a.state === 'working')), null, { timeout: 20000, polling: 800 });
  const after = (await api('/v1/hub')).accounts.find(a => a.provider === 'google');
  assert.deepEqual([after.id, after.state, after.granted.mail, after.capabilities.send], [beforeId, 'working', true, true]);
  await row('The autumn edit is here').waitFor();
  assert.equal(await page.locator('.mail-banners .notice', { hasText: 'no longer connected' }).count(), 0);
});

// ---- other sizes, the keyboard, the policy ---------------------------------------------------------------------------------------------------------------------
await step('at a tablet width the list and the open conversation take turns; at a phone width too, with nothing spilling sideways', async () => {
  await page.setViewportSize({ width: 1024, height: 768 }); await page.reload({ waitUntil: 'domcontentloaded' }); await row('The autumn edit is here').waitFor();
  assert.equal(await overflow(), false); await shot('20-tablet-list');
  await openThread('The autumn edit is here'); await frameReady(); await page.waitForTimeout(500);
  assert.equal(await overflow(), false); await shot('21-tablet-open');
  await page.setViewportSize({ width: 390, height: 844 }); await page.reload({ waitUntil: 'domcontentloaded' }); await row('The autumn edit is here').waitFor();
  assert.equal(await overflow(), false); await shot('22-phone-list');
  assert.equal(await page.locator('.md-detail').isVisible(), false, 'on a phone the list has the screen to itself');
  await openThread('The autumn edit is here'); await frameReady(); await page.waitForTimeout(600);
  assert.equal(await page.locator('.md-list').isVisible(), false);
  const fit = await inFrame((doc, frame) => ({ zoom: doc.body.style.zoom || '1', inside: doc.documentElement.scrollWidth <= frame.clientWidth + 1, width: frame.clientWidth }));
  assert.equal(fit.inside, true, 'a message wider than the screen is scaled to fit it');
  assert.equal(await overflow(), false); await shot('23-phone-newsletter');
  await page.getByRole('button', { name: 'Back to the list' }).click();
  await row('The autumn edit is here').waitFor(); assert.equal(await page.locator('.md-list').isVisible(), true);
  await openThread('Quarterly numbers for review'); await frameReady(); await page.waitForTimeout(400); assert.equal(await overflow(), false); await shot('24-phone-plain');
  await page.getByRole('button', { name: 'Back to the list' }).click();
  await page.getByRole('button', { name: 'Compose' }).click(); await page.getByRole('region', { name: 'New message' }).waitFor(); assert.equal(await overflow(), false); await shot('25-phone-compose');
  await page.getByRole('button', { name: 'Discard this draft' }).click();
  await page.setViewportSize({ width: 1728, height: 1000 }); await page.reload({ waitUntil: 'domcontentloaded' }); await row('The autumn edit is here').waitFor();
  await openThread('Quarterly numbers for review'); await frameReady(); await page.waitForTimeout(400); assert.equal(await overflow(), false); await shot('26-wide');
  await page.setViewportSize({ width: 1440, height: 900 });
});

await step('the keyboard alone: move, open, close, search, write', async () => {
  await page.reload({ waitUntil: 'domcontentloaded' }); await row('The autumn edit is here').waitFor(); await page.waitForTimeout(400);
  await page.keyboard.press('j'); await page.locator('.mail-subject').waitFor();
  const first = await page.locator('.mail-subject').textContent();
  await page.keyboard.press('j'); await waitFor(t => document.querySelector('.mail-subject')?.textContent !== t, first);
  await page.keyboard.press('k'); await waitFor(t => document.querySelector('.mail-subject')?.textContent === t, first);
  await page.keyboard.press('Escape'); await page.getByText('Select a conversation to read it here.').waitFor();
  await page.keyboard.press('/'); assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'Search mail');
  await page.keyboard.press('Escape'); await page.keyboard.press('c'); await page.getByRole('region', { name: 'New message' }).waitFor();
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'To');
  await page.keyboard.press('Escape');
  await page.keyboard.press('Tab'); const ring = await page.evaluate(() => { const el = document.activeElement; const s = getComputedStyle(el); return el && el !== document.body ? (s.outlineStyle !== 'none' || s.boxShadow !== 'none') : false; });
  assert.equal(ring, true, 'what has the keyboard focus shows it');
});

await step('nothing the app or a message did was refused by a content policy, and the server refused nothing the page asked', async () => { assert.deepEqual(framed.filter(u => !u.includes('/v1/hub/mail/frame?') && u !== 'about:blank'), [], 'a message\'s frame shows only the message\'s own page');
  assert.deepEqual(refused, []); assert.deepEqual(unexpected, []); });

console.log(results.join('\n'));
if (trace.length) console.log('\ntrace:\n' + trace.join('\n'));
if (process.env.MAIL_QA_TRACE) console.log('\nrequests:\n' + [...asked].filter(([, n]) => n >= 4).map(([k, n]) => `${String(n).padStart(4)}  ${k}`).join('\n'));
console.log(`\nscreenshots: ${out}`);
await browser.close();
process.exit(results.some(r => r.startsWith('FAIL')) ? 1 : 0);
