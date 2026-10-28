/** Optional tooling via PLAYWRIGHT_MODULE and AXE_MODULE; never operates on production. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? '../../browse/node_modules/playwright-core/index.mjs');
const { default: AxeBuilder } = await import(process.env.AXE_MODULE);
const browser = await chromium.launch({ channel: 'chrome' });
const findings = [];
try {
  for (const width of [1440, 390]) {
    const ctx = await browser.newContext({ viewport: { width, height: 960 }, hasTouch: width === 390 });
    const page = await ctx.newPage(); await page.goto('http://127.0.0.1:5179/app/gen-gallery');
    const component = page.getByRole('combobox', { name: /^Component/ }); await component.waitFor();
    const types = ['form', 'tabs', 'accordion', 'modal', 'wizard', 'decision_matrix', 'editable_table', 'kanban', 'calendar', 'line_chart', 'approval_request', 'error_retry', 'rule_builder'];
    for (const type of types) {
      await component.selectOption(type); await page.locator(`.gen-block[data-block]`).first().waitFor();
      await page.waitForFunction(() => !document.querySelector('.gen-doc')?.textContent.includes('Loading component'));
      const result = await new AxeBuilder({ page }).include('.gen-doc').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
      findings.push(...result.violations.map(v => ({ width, type, id: v.id, impact: v.impact, targets: v.nodes.map(n => n.target) })));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `${type} overflows at ${width}`);
      if (type === 'modal') {
        const trigger = page.getByRole('button', { name: /^Open / }); await trigger.click(); await page.getByRole('dialog').waitFor();
        await page.keyboard.press('Escape'); await page.getByRole('dialog').waitFor({ state: 'hidden' });
        assert.equal(await trigger.evaluate(el => el === document.activeElement), true);
      }
      if (type === 'tabs') {
        const tabs = page.getByRole('tab'); await tabs.first().focus(); await page.keyboard.press('ArrowRight');
        assert.equal(await tabs.nth(1).getAttribute('aria-selected'), 'true');
      }
    }
    await ctx.close();
  }
  // The renderer's documented maximum composition and dataset size, with actual sort/filter controls.
  const ctx = await browser.newContext(); const page = await ctx.newPage(); const start = performance.now();
  await page.goto('http://127.0.0.1:5179/app/chat/stress'); await page.getByRole('heading', { name: 'Stress table 24', exact: true }).waitFor();
  const mountedMs = performance.now() - start;
  const query = page.getByRole('searchbox', { name: 'Search rows' }).first();
  const changed = performance.now(); await query.fill('item 499'); await page.locator('.gen-block').first().getByText('Illustrative item 499', { exact: true }).waitFor();
  const filteredMs = performance.now() - changed;
  assert.ok(mountedMs < 10000, `Maximum composition mounted in ${mountedMs} ms`); assert.ok(filteredMs < 1500, `Filter took ${filteredMs} ms`);
  const report = { automatedAccessibilityViolations: findings, auditedFamilies: 13, viewports: [1440, 390], maximumComposition: { blocks: 24, datasetRows: 500, mountedMs, filteredMs } };
  await fs.mkdir('/tmp/lumina-ui-launch-evidence', { recursive: true });
  await fs.writeFile('/tmp/lumina-ui-launch-evidence/audit-results.json', JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report)); assert.equal(findings.length, 0); await ctx.close();
} finally { await browser.close(); }
