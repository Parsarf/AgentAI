import assert from 'node:assert/strict';
import { configuration } from './routing.mjs';
assert.equal(configuration().rewrites, undefined);
const c = configuration('https://backend.agentai-demo.com');
assert.equal(c.rewrites[0].destination, 'https://backend.agentai-demo.com/account/');
assert.deepEqual(c.rewrites.slice(1).map(r => r.source), ['/account/:path*','/auth/:path*','/v1/:path*']);
assert.ok(c.headers[0].headers.every(h => h.value === 'no-store' || h.value === '0'));
for (const origin of ['http://backend.agentai-demo.com','https://localhost','https://127.0.0.1',
  'https://10.0.0.1','https://[::1]','https://backend.local','https://backend.invalid',
  'https://user:password@backend.agentai-demo.com','https://backend.agentai-demo.com/path',
  'https://backend.agentai-demo.com?x=1','https://backend.agentai-demo.com#x',
  'https://backend.agentai-demo.com:444','garbage']) assert.throws(() => configuration(origin));
console.log('Vercel configuration checks passed (setup page, fixed routing, no-store, invalid origins).');
