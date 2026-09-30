/** Fixed customer routes. This module never reads credentials or contacts a server. */
export function configuration(origin = '') {
  const config = { framework: null, buildCommand: null, installCommand: null,
    outputDirectory: 'public', headers: [{ source: '/:path*', headers: [
      { key: 'Cache-Control', value: 'no-store' },
      { key: 'CDN-Cache-Control', value: 'no-store' },
      { key: 'Vercel-CDN-Cache-Control', value: 'no-store' },
      { key: 'x-vercel-enable-rewrite-caching', value: '0' }
    ] }] };
  if (!origin) return config;
  let url;
  try { url = new URL(origin); } catch { throw new Error('BACKEND_ORIGIN must be an HTTPS hostname'); }
  const host = url.hostname.toLowerCase();
  if (url.protocol !== 'https:' || url.username || url.password || url.port ||
      url.pathname !== '/' || url.search || url.hash || !host.includes('.') ||
      !/^[a-z0-9.-]+$/.test(host) || /^[0-9.]+$/.test(host) ||
      host.endsWith('.localhost') || host.endsWith('.local') || host.endsWith('.invalid') ||
      host.endsWith('.test') || host.endsWith('.example') || host === 'example.com') {
    throw new Error('BACKEND_ORIGIN must be a public HTTPS DNS hostname without credentials, path or port');
  }
  config.rewrites = [{ source: '/', destination: url.origin + '/account/' },
    ...['account', 'auth', 'v1'].map(prefix => ({
      source: '/' + prefix + '/:path*', destination: url.origin + '/' + prefix + '/:path*'
    }))];
  return config;
}
