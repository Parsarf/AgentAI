/** The router lives under /app. The edge can show the app at "/" (site root), where a /app-based router matches nothing and
 *  renders a blank screen; move the address bar to /app/ before the router starts. Returns the new URL, or null if fine. */
export function canonical(pathname: string, search = '', hash = ''): string | null {
  if (pathname === '/app' || pathname.startsWith('/app/')) return pathname === '/app' ? '/app/' + search + hash : null;
  const rest = pathname.replace(/^\/+/, '');
  return '/app/' + rest + search + hash;
}
