// Actual production UI, Django session/CSRF, encrypted store, SDK and task-owned relay; external service is a local fixture.
import { chromium } from '../../browse/node_modules/playwright-core/index.mjs';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
const origin = process.argv[2];
if (!/^https:\/\/localhost:\d+$/.test(origin || '')) throw new Error('Pass the local TLS fixture origin');
await mkdir('/tmp/lumina-mcp-ui', { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
try {
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width, height: 1000 } });
    const page = await context.newPage(); page.setDefaultTimeout(15000); page.setDefaultNavigationTimeout(15000);
    console.log('fixture stage', width, 'login'); const errors = []; page.on('pageerror', e => errors.push(e.message));
    const agent = async (name, args = {}) => {
      const response = await page.request.post(origin + '/__fixture__/agent', { data: { name, arguments: args } });
      const body = await response.json(); assert.ok(body.result, JSON.stringify(body)); return body.result;
    };
    await page.goto(origin + '/app/integrations');
    await page.getByLabel('Email', { exact: true }).fill('mcp-fixture@example.invalid');
    await page.getByLabel('Password', { exact: true }).fill('Lumina fixture password 2026!');
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.getByRole('heading', { name: 'MCP connections', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Custom server', exact: true }).waitFor();
    while (await page.locator('.mcp .tile:not(.add)').count()) {
      await page.locator('.mcp .tile:not(.add)').first().click();
      await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
      await page.getByRole('button', { name: 'Yes, disconnect', exact: true }).click();
      await page.getByRole('dialog').waitFor({ state: 'hidden' });
    }
    console.log('fixture stage', width, 'agent setup');
    // Agent creates an unknown endpoint. It appears in the SAME UI and cannot contact the server before review.
    const setup = await agent('lumina_mcp_setup', { name: 'Agent fixture', url: 'https://fixture.mcp-demo.net/mcp' });
    assert.equal(setup.isError, false); const connection = JSON.parse(setup.content[0].text); assert.equal(connection.setup_confirmed, false);
    await page.goto(origin + connection.manage_url);
    console.log('fixture stage', width, 'review');
    await page.getByText(/Added by Lumina/).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Check connection', exact: true }).isDisabled(), true);
    await page.getByRole('button', { name: 'Confirm server address', exact: true }).click();
    await page.getByText('Connected', { exact: true }).waitFor();
    console.log('fixture stage', width, 'connected');
    const echo = page.getByRole('radiogroup', { name: 'Echo: how Lumina uses it' });
    assert.equal(await echo.getByRole('radio', { name: 'Off', exact: true }).getAttribute('aria-checked'), 'true');
    await echo.getByRole('radio', { name: 'Ask', exact: true }).click();
    for (let attempt = 0; attempt < 40 && await echo.getByRole('radio', { name: 'Ask', exact: true }).getAttribute('aria-checked') !== 'true'; attempt++) await new Promise(r => setTimeout(r, 100));
    assert.equal(await echo.getByRole('radio', { name: 'Ask', exact: true }).getAttribute('aria-checked'), 'true');
    const duplicate = await agent('lumina_mcp_setup', { name: 'Duplicate', url: 'https://fixture.mcp-demo.net/mcp' });
    assert.equal(JSON.parse(duplicate.content[0].text).id, connection.id);
    const list = await agent('lumina_mcp_connections'); assert.equal(JSON.parse(list.content[0].text).connections.length, 1);
    const args = { text: 'Hello from UI ' + width };
    const pending = await agent('lumina_mcp_call', { tool: 'echo', arguments: args }); assert.equal(pending.isError, true); assert.match(pending.content[0].text, /approval required/i);
    await page.getByRole('button', { name: 'Close', exact: true }).click();
    await page.getByRole('button', { name: 'Approve', exact: true }).click();
    await page.getByText(/Approved for ten minutes/).waitFor();
    const result = await agent('lumina_mcp_call', { tool: 'echo', arguments: args }); assert.deepEqual(result.structuredContent, args);
    await page.getByRole('button', { name: /^Agent fixture, Connected/ }).click();
    await page.getByRole('button', { name: 'Connection settings', exact: true }).click();
    await page.getByLabel('How it signs in', { exact: true }).selectOption('header');
    await page.getByLabel('API-key header name', { exact: true }).fill('X-API-Key');
    await page.getByLabel('API key', { exact: true }).fill('fixture-header-secret');
    await page.getByRole('button', { name: 'Save and connect', exact: true }).click();
    await page.getByText('Connected', { exact: true }).waitFor();
    assert.equal(await page.locator('input[type="password"]').count(), 0);
    assert.equal(await echo.getByRole('radio', { name: 'Off', exact: true }).getAttribute('aria-checked'), 'true');
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await page.screenshot({ path: `/tmp/lumina-mcp-ui/connected-${width}.png`, fullPage: true });
    await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
    await page.getByRole('button', { name: 'Yes, disconnect', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    // Manual flow defaults to automatic and appears to the agent too.
    await page.getByRole('button', { name: 'Custom server', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: /Custom server/ }).click();
    assert.equal(await page.getByLabel('How it signs in', { exact: true }).inputValue(), 'auto');
    await page.getByLabel('Name', { exact: true }).fill('Manual fixture');
    await page.getByLabel('Server URL', { exact: true }).fill('https://fixture.mcp-demo.net/mcp');
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await page.getByText(/Added by you/).waitFor();
    const manual = JSON.parse((await agent('lumina_mcp_connections')).content[0].text).connections;
    assert.equal(manual.length, 1); assert.equal(manual[0].added_by, 'you');
    await page.getByRole('button', { name: 'Disconnect', exact: true }).click();
    await page.getByRole('button', { name: 'Yes, disconnect', exact: true }).click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ width, status: 'passed', flow: 'agent + manual → same connection → address review → SDK → tool approval → result → credential replacement → disconnect' }));
    await context.close();
  }
} finally { await browser.close(); }
