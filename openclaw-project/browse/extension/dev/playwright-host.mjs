// The extension's `host` (see ../src/executor.js) on Playwright instead of chrome.debugger / chrome.tabs, so the executor can run in any Chrome, with no extension loaded.
import { MAX_PAGES } from '../src/rules.js';

const EVENTS = ['Fetch.requestPaused', 'Page.javascriptDialogOpening'];

export class PlaywrightHost {
  constructor(context) { this.context = context; this.next = 1; this.tabsById = new Map(); this.order = []; this.listeners = []; this.adopting = new WeakMap(); context.on('page', p => { this.adopt(p).catch(() => {}); }); }
  adopt(page) {
    if (!this.adopting.has(page)) this.adopting.set(page, (async () => {
      if (this.order.length >= MAX_PAGES) { await page.close(); return null; }
      const id = this.next++, cdp = await this.context.newCDPSession(page);
      for (const ev of EVENTS) cdp.on(ev, p => this.listeners.forEach(f => f(id, ev, p)));
      this.tabsById.set(id, { page, cdp }); this.order.push(id);
      page.on('close', () => { this.order = this.order.filter(x => x !== id); this.tabsById.delete(id); });
      await this.onAdopt?.(id);
      return id;
    })());
    return this.adopting.get(page);
  }
  tabs() { return [...this.order]; }
  async newTab() { return this.adopt(await this.context.newPage()); }
  async closeTab(id) { await this.tabsById.get(id)?.page.close(); }
  send(id, method, params) { return this.tabsById.get(id).cdp.send(method, params); }
  onEvent(fn) { this.listeners.push(fn); }
  async activate(id) { await this.tabsById.get(id)?.page.bringToFront(); }
}
