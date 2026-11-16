// OKLCH <-> sRGB, and the measures the token generator and its test need (WCAG contrast, the OKLab distance). No dependencies.
const lin = c => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const gam = c => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

export function hexToRgb(hex) {
  const h = hex.replace('#', ''); const full = h.length === 3 ? [...h].map(x => x + x).join('') : h;
  return [0, 2, 4].map(i => parseInt(full.slice(i, i + 2), 16) / 255);
}
export function rgbToHex(rgb) { return '#' + rgb.map(c => Math.round(Math.min(1, Math.max(0, c)) * 255).toString(16).padStart(2, '0')).join(''); }

export function rgbToOklab([r, g, b]) {
  const [R, G, B] = [lin(r), lin(g), lin(b)];
  const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
  const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
  const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}
export function oklabToRgb([L, a, b]) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3, m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3, s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s, -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s].map(gam);
}
export function hexToOklch(hex) { const [L, a, b] = rgbToOklab(hexToRgb(hex)); return { l: L, c: Math.hypot(a, b), h: ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360 }; }
/** OKLCH -> hex. Out-of-gamut colours lose chroma until they fit, so the hue and the lightness are kept. */
export function oklchToHex({ l, c, h }) {
  const at = cc => oklabToRgb([l, cc * Math.cos((h * Math.PI) / 180), cc * Math.sin((h * Math.PI) / 180)]);
  let lo = 0, hi = c, rgb = at(c);
  if (rgb.some(x => x < -1e-4 || x > 1 + 1e-4)) { for (let i = 0; i < 24; i++) { const mid = (lo + hi) / 2; if (at(mid).some(x => x < -1e-4 || x > 1 + 1e-4)) hi = mid; else lo = mid; } rgb = at(lo); }
  return rgbToHex(rgb);
}
/** Distance in OKLab. About 0.02 is the smallest difference most people see between two flat colours side by side. */
export function deltaE(hexA, hexB) { const a = rgbToOklab(hexToRgb(hexA)), b = rgbToOklab(hexToRgb(hexB)); return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]); }
const luminance = rgb => { const [r, g, b] = rgb.map(lin); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
/** Composite a colour with alpha over an opaque one (both hex), for the contrast of translucent fills. */
export function over(fgHex, alpha, bgHex) { const f = hexToRgb(fgHex), b = hexToRgb(bgHex); return rgbToHex(f.map((x, i) => x * alpha + b[i] * (1 - alpha))); }
export function contrast(fgHex, bgHex) { const a = luminance(hexToRgb(fgHex)), b = luminance(hexToRgb(bgHex)); return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); }
