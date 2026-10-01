import { mkdirSync, rmSync, copyFileSync, writeFileSync } from 'node:fs';
import { configuration } from './routing.mjs';
const config = configuration(process.env.BACKEND_ORIGIN);
const output = new URL('./.vercel/output/', import.meta.url);
rmSync(output, { recursive: true, force: true });
mkdirSync(new URL('static/', output), { recursive: true });
copyFileSync(new URL('./public/robots.txt', import.meta.url), new URL('static/robots.txt', output));
const routes = [{ src: '^/.*$', headers: Object.fromEntries(config.headers[0].headers.map(h => [h.key,h.value])), continue: true }];
if (config.rewrites) {
  const backend = new URL(config.rewrites[0].destination).origin;
  routes.push(
    { src: '^/$', dest: backend + '/account/' },
    { src: '^/account/?$', dest: backend + '/account/' },
    { src: '^/account/(.*?)/?$', dest: backend + '/account/$1/' },
    { src: '^/(auth|v1)(/.*)?$', dest: backend + '/$1$2' }
  );
} else {
  copyFileSync(new URL('./public/index.html', import.meta.url), new URL('static/index.html', output));
}
routes.push({ handle: 'filesystem' }, { src: '^/.*$', status: 404 });
writeFileSync(new URL('config.json', output), JSON.stringify({version:3,routes},null,2)+'\n');
console.log(config.rewrites ? 'Customer HTTPS backend routing built.' : 'Initial setup page built.');
