# Existing VPS HTTPS edge

Caddyfile.getlumina is the deployed customer-only proxy for
backend.getlumina.pro. Caddy obtained a trusted certificate automatically.
The original /etc/caddy/Caddyfile is preserved as Caddyfile.before-agentai.
Install agentai-limits.conf as /etc/systemd/system/caddy.service.d/agentai-limits.conf.
Only account/auth/v1 paths reach loopback18800. Other paths return404.
Host is fixed to getlumina.pro; scheme and client IP are overwritten from the
actual proxy peer. Owner Gateway remains on loopback18789. No Vercel client-IP
header is trusted, so rate limits may aggregate Vercel proxy peers.

Canonical private application setting: AGENTAI_PUBLIC_ORIGIN=https://getlumina.pro.
Public Vercel Production setting: BACKEND_ORIGIN=https://backend.getlumina.pro.
Use systemctl restart caddy after caddy validate --config /etc/caddy/Caddyfile.
Rollback only this edge by restoring the saved Caddyfile or stopping Caddy.
Remove Production BACKEND_ORIGIN and redeploy to restore the setup page.
Do not reset account data or modify owner services.
