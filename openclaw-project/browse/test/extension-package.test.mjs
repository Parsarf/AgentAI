// The store zip: reproducible, complete, and nothing in it that should not be.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, existsSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, posix } from 'node:path';
import { chromium } from 'playwright-core';

const EXT = new URL('../extension/', import.meta.url).pathname;
// Python must never write its bytecode cache (__pycache__) next to the files it reads: Chrome refuses to load an extension folder that contains a name starting with an underscore.
const python = (args, options = {}) => spawnSync('python3', ['-B', ...args], { encoding: 'utf8', ...options, env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } });
const build = out => { const r = python([join(EXT, 'package.py'), '--out', out]); return { ...r, zip: join(out, 'lumina-browser-0.2.0.zip') }; };
const list = zip => spawnSync('unzip', ['-Z1', zip], { encoding: 'utf8' }).stdout.split('\n').filter(Boolean).sort();
const file = (zip, name) => spawnSync('unzip', ['-p', zip, name], { encoding: 'buffer' }).stdout;
const tmp = () => mkdtempSync(join(tmpdir(), 'lumina-zip-'));

test('the same files always give the same zip', () => {
  const a = build(tmp()), b = build(tmp());
  assert.equal(a.status, 0, a.stderr); assert.equal(b.status, 0, b.stderr);
  assert.deepEqual(readFileSync(a.zip), readFileSync(b.zip));
  assert.match(a.stdout, /sha256 [0-9a-f]{64}/);
});

test('it holds exactly what Chrome needs at run time, with the manifest at the top level', () => {
  const { zip } = build(tmp()), names = list(zip);
  assert.ok(names.includes('manifest.json'));
  for (const bad of names) assert.ok(!/^(dev|test|dist)\/|README|\.test\.|\.md$|package\.py|\.gitignore|icon\.svg/.test(bad), `does not belong in the store zip: ${bad}`);
  const manifest = JSON.parse(file(zip, 'manifest.json'));
  for (const f of [manifest.background.service_worker, manifest.action.default_popup, ...Object.values(manifest.icons), ...Object.values(manifest.action.default_icon)]) assert.ok(names.includes(f), `manifest names ${f}`);
  assert.equal(manifest.name, 'Lumina Browser'); assert.ok(manifest.description.length <= 132);
});

test('every import in the shipped scripts resolves to a file inside the zip, and none reaches outside it', () => {
  const { zip } = build(tmp()), names = new Set(list(zip));
  const scripts = [...names].filter(n => n.endsWith('.js')); assert.equal(scripts.length, 10);
  for (const s of scripts) {
    const code = file(zip, s).toString();
    for (const m of code.matchAll(/(?:from|import)\s*\(?\s*['"]([^'"]+)['"]/g)) {
      assert.ok(m[1].startsWith('./') && !m[1].includes('..'), `${s} imports ${m[1]}: only files inside the extension may be imported`);
      assert.ok(names.has(posix.normalize(posix.join(posix.dirname(s), m[1]))), `${s} imports ${m[1]}, which is not in the zip`);
    }
  }
  for (const page of ['popup.html', 'panel.html']) {
    const html = file(zip, page).toString();
    for (const m of html.matchAll(/(?:src|href)="([^"]+)"/g)) assert.ok(names.has(m[1]), `${page} uses ${m[1]}`);
  }
});

test('the icons are real PNGs of the sizes the manifest says', () => {
  const { zip } = build(tmp());
  for (const size of [16, 48, 128]) {
    const png = file(zip, `icons/icon-${size}.png`);
    assert.deepEqual([...png.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.equal(png.readUInt32BE(16), size); assert.equal(png.readUInt32BE(20), size);
  }
});

test('the builder refuses a manifest that is not ready for the store', () => {
  const py = `import json,sys; sys.path.insert(0, ${JSON.stringify(EXT)}); import package as p
m = json.load(open(${JSON.stringify(join(EXT, 'manifest.json'))}))
assert p.check(m) == [], p.check(m)
def bad(**kw): n = {**m, **kw}; return p.check(n)
print(json.dumps({'dev': bad(name='Lumina (development build)'), 'long': bad(description='x'*133), 'host': bad(host_permissions=['<all_urls>']), 'perm': bad(permissions=['debugger','tabGroups','storage','tabs']), 'noside': bad(permissions=['debugger','tabGroups','storage']), 'defaultpanel': bad(side_panel={'default_path': 'panel.html'}),
  'v2': bad(manifest_version=2), 'noicon': bad(icons={'16': m['icons']['16']}), 'missing': bad(icons={**m['icons'], '128': 'icons/nope.png'}), 'ver': bad(version='one')}))`;
  const r = python(['-c', py]); assert.equal(r.status, 0, r.stderr);
  const out = JSON.parse(r.stdout);
  for (const [name, problems] of Object.entries(out)) assert.ok(problems.length > 0, `${name} should be refused`);
});

test('the source icon, the manifest and the zip agree on the version', () => {
  const m = JSON.parse(readFileSync(join(EXT, 'manifest.json'), 'utf8'));
  assert.equal(m.version, '0.2.0'); assert.ok(existsSync(join(EXT, 'icons', 'logo-source.png')), 'the logo the icons are made from is kept with them');
});

test('the icons are the Lumina logo on a transparent background: 96 px star centred in the 128 px canvas, 16 px of margin all round', async () => {
  const { zip } = build(tmp());
  const browser = await chromium.launch({ executablePath: process.env.BROWSE_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  try {
    const page = await browser.newPage(); const want = { 16: 14, 48: 36, 128: 96 };
    for (const size of [16, 48, 128]) {
      const b64 = file(zip, `icons/icon-${size}.png`).toString('base64');
      const m = await page.evaluate(async b64 => {
        const i = new Image(); i.src = 'data:image/png;base64,' + b64; await i.decode();
        const c = document.createElement('canvas'); c.width = i.width; c.height = i.height; const g = c.getContext('2d'); g.drawImage(i, 0, 0);
        const d = g.getImageData(0, 0, i.width, i.height).data; let x0 = 999, y0 = 999, x1 = -1, y1 = -1, strong = 0;
        for (let y = 0; y < i.height; y++) for (let x = 0; x < i.width; x++) { const a = d[(y * i.width + x) * 4 + 3]; if (a > 8) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); } if (a > 200) strong++; }
        const corners = [0, i.width - 1].flatMap(x => [0, i.height - 1].map(y => d[(y * i.width + x) * 4 + 3]));
        const centre = [...d.slice(((i.height >> 1) * i.width + (i.width >> 1)) * 4, ((i.height >> 1) * i.width + (i.width >> 1)) * 4 + 3)];
        return { corners, w: x1 - x0 + 1, h: y1 - y0 + 1, left: x0, right: i.width - 1 - x1, top: y0, bottom: i.height - 1 - y1, strong, centre };
      }, b64);
      assert.deepEqual(m.corners, [0, 0, 0, 0], `${size}: the background is transparent`);
      assert.deepEqual([m.w, m.h], [want[size], want[size]], `${size}: the star is ${want[size]} px`);
      assert.deepEqual([m.left, m.right, m.top, m.bottom], Array(4).fill((size - want[size]) / 2), `${size}: centred with equal margins`);
      assert.ok(m.strong > 10 && m.centre[2] > m.centre[0], `${size}: the violet logo is there, not an empty canvas`);
    }
  } finally { await browser.close(); }
});

/** width and height from a JPEG's start-of-frame marker */
function jpegSize(buf) {
  assert.deepEqual([...buf.subarray(0, 3)], [0xff, 0xd8, 0xff], 'a JPEG');
  for (let i = 2; i < buf.length - 9;) {
    if (buf[i] !== 0xff) { i++; continue; }
    const marker = buf[i + 1];
    if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) return { h: buf.readUInt16BE(i + 5), w: buf.readUInt16BE(i + 7) };
    i += 2 + buf.readUInt16BE(i + 2);
  }
  throw new Error('no frame header');
}

test('the store screenshots are what the store accepts: one to five JPEGs of exactly 1280x800, kept out of the extension zip', () => {
  const dir = join(EXT, 'store', 'screenshots'), shots = readdirSync(dir).filter(n => n.endsWith('.jpg')).sort();
  assert.ok(shots.length >= 1 && shots.length <= 5, `${shots.length} screenshots`);
  for (const name of shots) assert.deepEqual(jpegSize(readFileSync(join(dir, name))), { w: 1280, h: 800 }, name);
  assert.ok(!list(build(tmp()).zip).some(n => n.startsWith('store/') || n.endsWith('.jpg')));
});

test('the extension folder holds nothing Chrome would refuse to load (no name starting with an underscore, such as Python\'s __pycache__)', () => {
  const found = [];
  (function walk(dir) { for (const e of readdirSync(dir, { withFileTypes: true })) { if (e.name.startsWith('_')) found.push(join(dir, e.name).replace(EXT, '')); if (e.isDirectory()) walk(join(dir, e.name)); } })(EXT);
  assert.deepEqual(found, [], `Chrome reserves names starting with "_" and will not load the folder while these exist: ${found.join(', ')}. Delete them (they are only caches) and find what wrote them.`);
});
