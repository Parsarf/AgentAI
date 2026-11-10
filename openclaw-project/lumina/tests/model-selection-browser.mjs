/** Start preview_chat.py after building. Synthetic settings; no real API keys. */
import assert from 'node:assert/strict';
import { chromium } from '../../browse/node_modules/playwright-core/index.mjs';
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  for (const width of [390, 1440]) {
    const context = await browser.newContext({ viewport: { width, height: 1000 } });
    const page = await context.newPage();
    let busy = false;
    const state = { available: true, configured: true, selected: 'lumina-default', lumina_models: [{ id: 'lumina-default', name: 'Lumina' }],
      keys: [{ id: 'key:one', model: 'my-model', host: 'models.example.org', hint: '1234' }, { id: 'key:two', model: 'another-model', host: 'other.example.org', hint: '5678' }] };
    await page.route('**/v1/model-key', r => r.fulfill({ json: state }));
    await page.route('**/v1/model-key/select', r => {
      if (busy) return r.fulfill({ status: 409, json: { error: 'model_busy', detail: 'Finish or stop your pending tasks before changing models or keys.' } });
      state.selected = r.request().postDataJSON().id;
      return r.fulfill({ json: state });
    });
    await page.route('**/v1/csrf', r => r.fulfill({ json: { csrf_token: 'synthetic' } }));
    await page.goto('http://127.0.0.1:5178/app/settings');
    await page.getByRole('tab', { name: 'Assistant', exact: true }).click();
    const selector = page.getByRole('combobox', { name: 'Assistant model' });
    await selector.waitFor();
    assert.equal(await selector.locator('optgroup[label="Lumina"] option').count(), 1);
    for (const id of ['key:one', 'key:two', 'lumina-default']) {
      await selector.selectOption(id);
      const saved = page.waitForResponse(r => r.url().endsWith('/v1/model-key/select') && r.status() === 200);
      await page.getByRole('button', { name: 'Use model' }).click(); await saved;
      await page.waitForFunction(() => [...document.querySelectorAll('button')].find(b => b.textContent === 'Use model')?.disabled);
      assert.equal(state.selected, id); assert.equal(state.keys.length, 2);
    }
    busy = true; await selector.selectOption('key:one'); await page.getByRole('button', { name: 'Use model' }).click();
    await page.getByRole('alert').filter({ hasText: 'Finish or stop' }).waitFor();
    assert.equal(state.selected, 'lumina-default');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.locator('#own-model').screenshot({ path: `/private/tmp/lumina-model-selection-${width}.png` });
    console.log(`Chrome ${width}px switching, retained keys, conflict and layout: passed`);
    await context.close();
  }
} finally { await browser.close(); }
