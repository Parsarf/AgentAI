/** Start preview_chat.py and preview_genui.py, then node tests/launch-genui.mjs [chromium|firefox|webkit]. Synthetic data only. */
const { chromium, firefox, webkit } = await import(process.env.PLAYWRIGHT_MODULE ?? '../../browse/node_modules/playwright-core/index.mjs');
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const engine = process.argv[2] ?? 'chromium';
const browser = await ({ chromium, firefox, webkit })[engine].launch({ headless: true, ...(engine === 'chromium' ? { channel: 'chrome' } : {}) });
const output = process.env.LUMINA_EVIDENCE_DIR ?? '/tmp/lumina-ui-launch-evidence';
await fs.mkdir(output, { recursive: true });
const checks = [];
const check = (name, detail = {}) => checks.push({ name, ...detail, passed: true });
try {
  for (const width of [1440, 390]) for (const motion of ['no-preference', 'reduce']) {
    const ctx = await browser.newContext({ viewport: { width, height: 960 }, reducedMotion: motion, ...(engine !== 'firefox' ? { hasTouch: width === 390 } : {}) });
    const page = await ctx.newPage();
    const errors = []; page.on('pageerror', error => errors.push(error.stack ?? error.message));
    for (const fixture of ['working', 'completed', 'long', 'multiple']) {
      await page.goto(`http://127.0.0.1:5178/app/chat/${fixture}`);
      await page.waitForFunction(() => document.documentElement.dataset.layoutCheck === 'passed');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    }
    check('chat layouts', { width, motion });
    await page.goto('http://127.0.0.1:5179/app/chat/c-a');
    const quantity = page.getByRole('spinbutton', { name: /^Quantity/ }); await quantity.waitFor();
    await quantity.fill('40'); await page.getByRole('button', { name: /Calculate total/ }).click();
    await page.getByText('Enter a number from 1 up to 20.').waitFor(); assert.equal(await quantity.getAttribute('aria-invalid'), 'true');
    await page.waitForFunction(() => document.activeElement?.getAttribute('aria-invalid') === 'true');
    await quantity.fill('4'); await page.getByRole('spinbutton', { name: 'Scenario quantity' }).fill('5');
    await page.getByText('Result: 50 USD').waitFor();
    const filter = page.getByRole('searchbox', { name: 'Search rows' });
    await filter.fill('Beta'); await page.getByText('Changes saved', { exact: true }).waitFor();
    await Promise.all([page.waitForResponse(r => r.url().endsWith('/events') && r.request().method() === 'POST'), page.getByRole('button', { name: /Calculate total/ }).click()]); await page.getByText('$40', { exact: true }).waitFor();
    await page.reload(); await quantity.waitFor(); assert.equal(await quantity.inputValue(), '4'); assert.equal(await filter.inputValue(), 'Beta');
    await page.getByText('Result: 50 USD').waitFor();
    let drop = true;
    await page.route('**/v1/genui/artifacts/*/state', async route => { if (drop) { drop = false; await route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"temporarily_unavailable"}' }); } else await route.continue(); });
    await quantity.fill('6'); await page.getByRole('button', { name: 'Retry saving' }).click();
    await page.getByText('Changes saved', { exact: true }).waitFor(); assert.equal(await quantity.inputValue(), '6');
    check('validation, same-artifact update, persistence and save recovery', { width, motion });
    await page.evaluate(() => { document.documentElement.style.fontSize = '200%'; });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await page.screenshot({ path: `${output}/${engine}-${width}-${motion}.png`, fullPage: true });
    assert.deepEqual(errors, []); await ctx.close();
  }
  const ctx = await browser.newContext(); const a = await ctx.newPage(); const b = await ctx.newPage();
  await a.goto('http://127.0.0.1:5179/app/chat/c-a'); await b.goto('http://127.0.0.1:5179/app/chat/c-a');
  await a.getByRole('spinbutton', { name: /^Quantity/ }).waitFor(); await b.getByRole('spinbutton', { name: /^Quantity/ }).waitFor();
  await a.getByRole('spinbutton', { name: /^Quantity/ }).fill('8'); await a.getByText('Changes saved', { exact: true }).waitFor();
  await b.getByRole('spinbutton', { name: /^Quantity/ }).fill('9'); await b.getByRole('button', { name: 'Keep my edits' }).waitFor();
  await b.getByRole('button', { name: 'Use saved edits' }).click();
  assert.equal(await b.getByRole('spinbutton', { name: /^Quantity/ }).inputValue(), '8');
  check('two-tab conflict resolution'); await ctx.close();
  await fs.writeFile(`${output}/${engine}-results.json`, JSON.stringify({ engine, version: browser.version(), checks }, null, 2));
  console.log(JSON.stringify({ engine, version: browser.version(), checks }));
} finally { await browser.close(); }
