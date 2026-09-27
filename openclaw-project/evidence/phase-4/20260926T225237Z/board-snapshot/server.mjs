import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
const root = process.cwd();
const port = Number(process.env.PORT || 3000);
const paths = new Map([['/', 'index.html'], ['/styles.css', 'styles.css'], ['/src/app.mjs', 'src/app.mjs'], ['/src/board.mjs', 'src/board.mjs']]);
const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8' };
http.createServer(async (request, response) => {
  const file = paths.get(new URL(request.url, 'http://localhost').pathname);
  if (!file) { response.writeHead(404); response.end('Not found'); return; }
  try {
    const body = await fs.readFile(path.join(root, file));
    response.writeHead(200, { 'content-type': types[path.extname(file)], 'cache-control': 'no-store' });
    response.end(body);
  } catch { response.writeHead(500); response.end('Server error'); }
}).listen(port, '127.0.0.1', () => console.log(`Task board: http://127.0.0.1:${port}`));
