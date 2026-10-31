// Plays the extension for platform tests and demos: the real executor in a headless Chrome, speaking to the platform's device gateway exactly as src/background.js does
// (hello with a pairing code or a token, then the runner commands). It also serves the mock shop, so a test has a page to browse.
//   node dev/device-sim.mjs --url ws://127.0.0.1:18802/v1/device (--pair CODE | --token TOKEN) [--origin chrome-extension://sim]
// Prints one JSON line per event on stdout: {"ready":true,"shop":"http://127.0.0.1:PORT"}, {"welcome":{...}}, {"closed":code}.
import { chromium } from 'playwright-core';
import { startSite } from '../../fixtures/site.mjs';
import { Executor } from '../src/executor.js';
import { PlaywrightHost } from './playwright-host.mjs';

const arg = name => { const i = process.argv.indexOf('--' + name); return i > 0 ? process.argv[i + 1] : undefined; };
const say = o => process.stdout.write(JSON.stringify(o) + '\n');
const CHROME = process.env.BROWSE_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

const site = await startSite();
const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: ['--no-first-run'] });
const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const host = new PlaywrightHost(context);
const ex = new Executor(host, { allowLoopback: true });
host.onAdopt = id => ex.adopt(id);
say({ ready: true, shop: `http://127.0.0.1:${site.port}` });

const ws = new WebSocket(arg('url'), { headers: { Origin: arg('origin') || 'chrome-extension://simulatedextensionidsimulatedext' } });
let queue = Promise.resolve();
ws.onopen = () => ws.send(JSON.stringify(arg('pair') ? { hello: 1, pair: arg('pair'), label: 'Simulated Chrome', version: 'sim' } : { hello: 1, token: arg('token'), version: 'sim' }));
ws.onmessage = e => { queue = queue.then(async () => {
  const msg = JSON.parse(e.data);
  if (msg.welcome) return say({ welcome: msg });
  if (msg.pong || msg.cmd === undefined) return;
  ws.send(JSON.stringify({ ...(await ex.handle(msg)), id: msg.id }));
}); };
ws.onclose = async e => { say({ closed: e.code, reason: e.reason }); await ex.handle({ cmd: 'close' }).catch(() => {}); await browser.close().catch(() => {}); site.close(); process.exit(0); };
ws.onerror = () => {};
process.on('SIGTERM', () => ws.close());
