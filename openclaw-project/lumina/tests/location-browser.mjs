/** Run preview_chat.py first. Real Chrome geolocation API, synthetic coordinates. */
import assert from 'node:assert/strict';
import { chromium } from '../../browse/node_modules/playwright-core/index.mjs';
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  for (const width of [390, 1440]) for (const outcome of ['granted', 'denied', 'waiting']) {
    const context = await browser.newContext({ viewport: { width, height: 900 },
      ...(outcome === 'granted' ? { permissions: ['geolocation'], geolocation: { latitude: 37.78, longitude: -122.42, accuracy: 30 } } : {}) });
    const page = await context.newPage();
    let answer;
    if (outcome === 'waiting') await page.addInitScript(() => {
      Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition() {} }, configurable: true });
    });
    await page.route('**/v1/requests', route => route.fulfill({ json: { requests: [{ id: 'fixture-working', state: 'running', message: 'Restaurants near me', cancel_requested: 0 }] } }));
    // The shell asks for a location only while a task is working, and reads that from the shared task state.
    await page.route('**/v1/work', route => route.fulfill({ json: { rev: 'loc', attention: 0, tasks: [{ id: 'fixture-working', conversation_id: 'working', title: 'Restaurants near me', follows: null, created_epoch: Math.floor(Date.now() / 1000), state: 'running', phase: 'working', label: 'Thinking', tone: 'live',
      activity: null, now: [], ahead: null, attention: null, attention_label: '', outcome: null, verification: null, note: '', goal: false, continuing: false, retry_of: null, needs: [], steps: 0,
      controls: { stop: true, pause: false, resume: false, retry: false, goal_resume: false, goal_clear: false, steer: true } }] } }));
    await page.route('**/v1/location', route => route.fulfill({ json: { request: answer ? null : { id: 'testloc', expires_epoch: Math.floor(Date.now()/1000) + 120 } } }));
    await page.route('**/v1/csrf', route => route.fulfill({ json: { csrf_token: 'fixture' } }));
    await page.route('**/v1/location/testloc', async route => {
      const body = route.request().postDataJSON();
      if (body.action === 'respond') answer = body;
      await route.fulfill({ json: { accepted: true, status: body.status || 'pending' } });
    });
    await page.goto('http://127.0.0.1:5178/app/chat/working');
    if (outcome === 'waiting') {
      await page.getByRole('region', { name: 'Location permission' }).waitFor();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
      await page.screenshot({ path: `/private/tmp/lumina-location-${width}.png` });
      await page.getByRole('button', { name: 'Continue without location' }).click();
    }
    for (let i = 0; !answer && i < 80; i++) await page.waitForTimeout(250);
    assert.equal(answer?.status, outcome === 'granted' ? 'granted' : 'denied');
    if (outcome === 'granted') assert.equal(answer.position.latitude, 37.78);
    console.log(`Chrome ${width}px ${outcome}: passed`);
    await context.close();
  }
} finally { await browser.close(); }
