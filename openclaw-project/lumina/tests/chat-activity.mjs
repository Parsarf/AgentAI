// Run after npm run build and python3 tests/preview_chat.py. Synthetic API data only.
import { chromium } from '../../browse/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const out = process.env.CHAT_QA_OUTPUT || '/tmp/lumina-chat-activity';
await mkdir(out, { recursive: true });
try {
  const sample = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  await sample.setContent('<html style="background:#faf9f6;color:#222;font:24px system-ui;padding:60px"><h1>Example shop</h1><p>Synthetic browser preview for layout verification</p><hr><h2>Search results</h2><p>Item one · Item two · Item three</p></html>');
  const shot = await sample.screenshot({ type: 'jpeg' }); await sample.close();
  const results = [];
  for (const width of [1440, 390]) for (const motion of ['no-preference', 'reduce']) {
    const page = await browser.newPage({ viewport: { width, height: 1000 }, reducedMotion: motion });
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    for (const scenario of ['working', 'completed', 'long', 'multiple']) {
      await page.goto(`http://127.0.0.1:5178/app/chat/${scenario}`);
      await page.waitForFunction(() => document.documentElement.dataset.layoutCheck === 'passed');
      assert.equal(await page.locator('.thread-head').count(), 0);
      assert.equal(await page.getByRole('button', { name: 'Stop task', exact: true }).count(), scenario === 'working' ? 1 : 0);
    }
    let stopped = false; let command = 'none';
    await page.route('**/v1/**', async route => {
      const url = new URL(route.request().url());
      const json = body => route.fulfill({ json: body });
      if (url.pathname === '/v1/app') {
        const response = await route.fetch(); const body = await response.json();
        body.features.browse = true; return json(body);
      }
      if (url.pathname === '/v1/requests') return json({ requests: [{ id: 'fixture-working', state: stopped ? 'cancelled' : 'running', created_epoch: Math.floor(Date.now() / 1000) - 82, message: 'Find the available items', conversation_id: 'working' }] });
      if (url.pathname.endsWith('/cancel')) { stopped = true; return json({ request: { state: 'cancelled' } }); }
      if (stopped && url.pathname.endsWith('/messages')) return json({ messages: Number(url.searchParams.get('after') || 0) < 2 ? [{ id: 2, request_id: 'fixture-working', provenance: 'system', content: 'Stopped at your request. Send a follow-up to continue.', created_at: '' }] : [], tasks: [{ id: 'fixture-working', state: 'cancelled', cancel_requested: true, created_epoch: Math.floor(Date.now() / 1000) - 82 }], has_more: false });
      if (url.pathname.includes('/tasks/') && url.pathname.endsWith('/events')) {
        const after = Number(url.searchParams.get('after') || 0);
        const events = [{ sequence: 1, kind: 'activity', payload: { ref: 'browser', category: 'browse', status: 'running', label: 'Opened example shop' } }];
        if (command !== 'none') events.push({ sequence: 2, kind: 'activity', payload: { ref: 'cmd', category: 'command', status: 'running', label: 'Ran a command', detail: 'python report.py' } });
        if (command === 'done') events.push({ sequence: 3, kind: 'activity', payload: { ref: 'cmd', category: 'command', status: 'done', label: 'Ran a command', detail: 'python report.py', output: 'Report saved' } });
        return json({ events: events.filter(e => e.sequence > after) });
      }
      if (url.pathname === '/v1/browse/fixture-working') return json({ goal: 'Find the available items', status: stopped ? 'cancelled' : 'running', url: 'https://example.com', created_epoch: Math.floor(Date.now() / 1000) - 82, takeover: false, pending_action: null, events: Number(url.searchParams.get('since')) ? [] : [{ n: 1, kind: 'screenshot', file: 'preview.jpg' }] });
      if (url.pathname.endsWith('/shot/preview.jpg')) return route.fulfill({ contentType: 'image/jpeg', body: shot });
      if (url.pathname.endsWith('/live')) return route.fulfill({ status: 404, json: {} });
      return route.continue();
    });
    await page.goto('http://127.0.0.1:5178/app/chat/working');
    const more = page.getByRole('button', { name: 'Read more', exact: true }); await more.click();
    const activity = page.getByRole('region', { name: 'Live task activity' });
    await activity.getByAltText('The page Lumina is working on', { exact: true }).waitFor({ state: 'visible' });
    await page.waitForFunction(() => document.documentElement.dataset.layoutCheck === 'passed');
    assert.equal(await activity.getByRole('button', { name: 'Stop', exact: true }).count(), 0);
    assert.equal(await page.getByRole('button', { name: 'Stop task' }).evaluate(el => !!el.closest('.composer')), true);
    assert.equal(await activity.getByRole('tab', { name: 'Terminal' }).count(), 0);
    assert.equal(await activity.getByRole('tab', { name: 'Activity' }).getAttribute('aria-selected'), 'true');
    await page.screenshot({ path: `${out}/activity-${width}-${motion}.png`, fullPage: true });
    command = 'running';
    await activity.getByRole('log', { name: 'Terminal', exact: true }).getByText('python report.py').waitFor();
    assert.equal(await activity.getByRole('tab', { name: 'Terminal' }).getAttribute('aria-selected'), 'true');
    command = 'done';
    await activity.getByRole('log', { name: 'Activity log' }).getByText('Report saved', { exact: true }).waitFor();
    assert.equal(await activity.getByRole('tab', { name: 'Terminal' }).count(), 0);
    assert.equal(await activity.getByRole('tab', { name: 'Activity' }).getAttribute('aria-selected'), 'true');
    await page.getByRole('button', { name: 'Read less' }).click();
    assert.equal(await page.locator('.chat-activity').count(), 0);
    await more.click();
    await page.getByRole('button', { name: 'Stop task' }).click();
    await page.getByText('Stopped at your request. Send a follow-up to continue.', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Send message' }).waitFor();
    assert.equal(await page.locator('.agent-thinking [data-testid="orb"], .agent-thinking canvas, .chat-activity .dot-s.running').count(), 0);
    assert.equal(await page.getByText('Stopped at your request. Send a follow-up to continue.', { exact: true }).evaluate(el => !!el.closest('.bubble.agent')), true);
    await page.waitForFunction(() => document.documentElement.dataset.layoutCheck === 'passed');
    // The full Live view uses the same default and command visibility rules.
    stopped = false; command = 'none';
    await page.goto('http://127.0.0.1:5178/app/live/fixture-working');
    await page.getByRole('tab', { name: 'Activity', exact: true }).waitFor();
    assert.equal(await page.getByRole('tab', { name: 'Terminal' }).count(), 0);
    command = 'running';
    await page.getByRole('log', { name: 'Terminal', exact: true }).getByText('python report.py').waitFor();
    command = 'done';
    await page.getByRole('log', { name: 'Activity log' }).getByText('Report saved', { exact: true }).waitFor();
    assert.equal(await page.getByRole('tab', { name: 'Terminal' }).count(), 0);
    assert.deepEqual(errors, []);
    results.push({ width, motion, layout: 'passed', inlineBrowser: 'passed', stop: 'passed' });
    await page.close();
  }
  console.log(JSON.stringify({ results, screenshots: out }, null, 2));
} finally { await browser.close(); }
