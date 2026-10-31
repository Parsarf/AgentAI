// Renders icons/logo-source.png (the Lumina logo) to the three PNG sizes the manifest names, on a transparent background.
// The logo is cropped to its own edges first (the source has margin built in), then drawn at 75% of the canvas, centred: 96 px in the 128 px icon, 16 px of margin all round.
// The 16 px toolbar icon uses 14 px instead, so the star stays readable. Each size is drawn at its own size, stepping down by halves, so the small ones stay clean.
//   node dev/make-icons.mjs
import { readFileSync, writeFileSync } from 'node:fs';
import { chromium } from 'playwright-core';

const SOURCE = readFileSync(new URL('../icons/logo-source.png', import.meta.url)).toString('base64');
const CHROME = process.env.BROWSE_CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const SIZES = { 16: 14, 48: 36, 128: 96 };      // canvas -> logo
const browser = await chromium.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage();
await page.setContent('<!doctype html><canvas></canvas>');
const out = await page.evaluate(async ({ b64, sizes }) => {
  const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
  const canvas = (w, h = w) => { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; };
  const draw = (src, w, h = w) => { const c = canvas(w, h), g = c.getContext('2d'); g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high'; g.drawImage(src, 0, 0, w, h); return c; };
  // where the logo really is: the box of everything that is not transparent
  const full = canvas(img.naturalWidth); full.getContext('2d').drawImage(img, 0, 0);
  const { data, width, height } = full.getContext('2d').getImageData(0, 0, img.naturalWidth, img.naturalWidth);
  let x0 = width, y0 = height, x1 = -1, y1 = -1;
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) if (data[(y * width + x) * 4 + 3] > 8) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
  const bw = x1 - x0 + 1, bh = y1 - y0 + 1;                                   // the source star is 1024 x 1041: a four-point star is symmetric, so it is scaled to an exact square (a 2% stretch)
  const crop = canvas(bw, bh); crop.getContext('2d').drawImage(img, -x0, -y0);
  const result = {};
  for (const [size, logo] of Object.entries(sizes)) {
    let cur = crop, w = bw, h = bh;
    while (Math.min(w, h) / 2 > logo) { w = Math.round(w / 2); h = Math.round(h / 2); cur = draw(cur, w, h); }
    const final = canvas(+size), g = final.getContext('2d'); g.imageSmoothingEnabled = true; g.imageSmoothingQuality = 'high';
    const o = (size - logo) / 2; g.drawImage(cur, o, o, logo, logo);
    result[size] = final.toDataURL('image/png').split(',')[1];
  }
  return { result, box: [x0, y0, x1, y1] };
}, { b64: SOURCE, sizes: SIZES });
for (const [size, data] of Object.entries(out.result)) writeFileSync(new URL(`../icons/icon-${size}.png`, import.meta.url), Buffer.from(data, 'base64'));
console.log('logo found at', out.box.join(','), 'in the source');
await browser.close();
