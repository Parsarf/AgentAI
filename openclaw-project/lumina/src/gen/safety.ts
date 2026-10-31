// Everything the model writes is untrusted. These are the only text and URL shapes a block may carry.
import { z } from 'zod';

const CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/;
const HTMLISH = /<\s*\/?\s*[a-z!][^>]*>/i;
const ZERO_WIDTH_BIDI = /[‪-‮⁦-⁩]/;       // bidi overrides can disguise text (a spoofed link label), so they never pass

/** Plain text: bounded, no control characters, no HTML-looking markup, no bidi overrides. Markdown content uses `md` (HTML is still refused; the renderer also skips raw HTML). */
export const text = (max: number, min = 1) => z.string().min(min).max(max)
  .refine(s => !CONTROL.test(s), 'control characters are not allowed')
  .refine(s => !HTMLISH.test(s), 'HTML is not allowed')
  .refine(s => !ZERO_WIDTH_BIDI.test(s), 'bidi overrides are not allowed');
export const md = (max: number, min = 1) => text(max, min);
export const ident = z.string().regex(/^[a-z][a-z0-9_-]{0,47}$/, 'ids are lowercase letters, digits, - or _');

/** http(s) with no credentials, no javascript:/data:/file:, bounded. Used only for links the person clicks; nothing is fetched automatically. */
export function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 500 || CONTROL.test(value)) return null;
  try {
    const u = new URL(value);
    return ['http:', 'https:'].includes(u.protocol) && !u.username && !u.password && !!u.hostname ? u.href : null;
  } catch { return null; }
}
export const httpUrl = z.string().max(500).refine(v => safeHttpUrl(v) !== null, 'must be an http(s) link without credentials');

/** Internal app routes a navigate.internal action may open. Anything else is refused. */
export const INTERNAL_ROUTES = ['/chat', '/tasks', '/files', '/live', '/history', '/calendar', '/settings'] as const;
export function safeInternalPath(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > 200 || CONTROL.test(value) || value.includes('\\') || value.startsWith('//')) return null;
  const [path] = value.split(/[?#]/);
  if (path.split('/').includes('..')) return null;
  return INTERNAL_ROUTES.some(r => path === r || path.startsWith(r + '/')) ? value : null;
}

/** A path inside the customer's own files: relative, no traversal, no control characters. */
export function safeFilePath(value: unknown): string | null {
  if (typeof value !== 'string' || !value || value.length > 300 || CONTROL.test(value) || value.includes('\\') || value.startsWith('/') || /^[a-z][a-z0-9+.-]*:/i.test(value)) return null;
  return value.split('/').some(s => s === '..' || s === '.' || s === '') ? null : value;
}
export const filePath = z.string().max(300).refine(v => safeFilePath(v) !== null, 'must be a relative path inside your files');

/** Images are never loaded from arbitrary addresses (that would reveal the reader to a third party and could carry data out in the URL).
 *  An image is a file in the customer's own files (`file:<path>`) or an app-served path. Anything else is shown as a link to open. */
export function safeAssetSrc(ref: unknown, base = '/v1/files/content?path='): string | null {
  if (typeof ref !== 'string') return null;
  if (ref.startsWith('file:')) { const p = safeFilePath(ref.slice(5)); return p ? base + encodeURIComponent(p) : null; }
  return null;
}
export const assetRef = z.string().max(320).refine(v => v.startsWith('file:') && safeFilePath(v.slice(5)) !== null, 'must be file:<relative path> in your files');
