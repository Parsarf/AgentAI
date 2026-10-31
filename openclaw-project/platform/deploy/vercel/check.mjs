import assert from 'node:assert/strict';
import { configuration } from './routing.mjs';
assert.equal(configuration().rewrites, undefined);
const c = configuration('https://backend.agentai-demo.com');
assert.equal(c.rewrites[0].destination, 'https://backend.agentai-demo.com/app/');
assert.deepEqual(c.rewrites.slice(1).map(r => r.source), ['/account/:path*','/auth/:path*','/v1/:path*','/app/:path*']);
assert.ok(c.headers[0].headers.every(h => h.value === 'no-store' || h.value === '0'));
for (const origin of ['http://backend.agentai-demo.com','https://localhost','https://127.0.0.1',
  'https://10.0.0.1','https://[::1]','https://backend.local','https://backend.invalid',
  'https://user:password@backend.agentai-demo.com','https://backend.agentai-demo.com/path',
  'https://backend.agentai-demo.com?x=1','https://backend.agentai-demo.com#x',
  'https://backend.agentai-demo.com:444','garbage']) assert.throws(() => configuration(origin));
console.log('Vercel configuration checks passed (setup page, fixed routing, no-store, invalid origins).');

// Verify actual Build Output API rules, including Django trailing slashes.
const { execFileSync } = await import('node:child_process');
const { readFileSync, existsSync } = await import('node:fs');
const { fileURLToPath } = await import('node:url');
const directory = fileURLToPath(new URL('.', import.meta.url));
function build(origin) {
  execFileSync(process.execPath, ['build.mjs'], {cwd:directory,env:{...process.env,BACKEND_ORIGIN:origin}});
  return JSON.parse(readFileSync(new URL('./.vercel/output/config.json',import.meta.url),'utf8'));
}
const initial=build('');assert.equal(initial.version,3);assert.ok(existsSync(new URL('./.vercel/output/static/index.html',import.meta.url)));
const live=build('https://backend.agentai-demo.com');assert.equal(existsSync(new URL('./.vercel/output/static/index.html',import.meta.url)),false);
function target(path) {
  for(const route of live.routes) {
    if(!route.dest)continue;
    const pattern=new RegExp(route.src);
    if(pattern.test(path))return path.replace(pattern,route.dest);
  }
  return null;
}
assert.equal(target('/'),'https://backend.agentai-demo.com/app/');
assert.equal(target('/account/'),'https://backend.agentai-demo.com/account/');
assert.equal(target('/account/login/'),'https://backend.agentai-demo.com/account/login/');
assert.equal(target('/account/login'),'https://backend.agentai-demo.com/account/login/');
assert.equal(target('/auth/login'),'https://backend.agentai-demo.com/auth/login');
assert.equal(target('/v1/requests'),'https://backend.agentai-demo.com/v1/requests');
assert.equal(target('/app/'),'https://backend.agentai-demo.com/app/');
assert.equal(target('/internal/'),null);
build('');console.log('Build output checks passed (root, account slashes, APIs and internal exclusion).');
// The public privacy policy is served at /privacy in both modes, ahead of the filesystem, and is never sent to the server.
assert.equal(target('/privacy'), '/privacy.html'); assert.equal(target('/privacy/'), '/privacy.html'); assert.equal(target('/privacy.html'), null);
assert.ok(existsSync(new URL('./.vercel/output/static/privacy.html', import.meta.url)));
const setup = build(''); assert.ok(setup.routes.some(r => r.src === '^/privacy/?$' && r.dest === '/privacy.html')); assert.ok(existsSync(new URL('./.vercel/output/static/privacy.html', import.meta.url)));
console.log('Vercel privacy page checks passed.');
