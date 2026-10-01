# Publish AgentAI from GitHub to Vercel

This folder is the Vercel project. It can deploy immediately without server
credentials: when BACKEND_ORIGIN is absent, visitors see a setup page and no
login controls. When configured, fixed rewrites serve account HTML and APIs
from the VPS. SQLite, sessions, provider secrets and workers stay on the VPS.
Native agent processing is still disabled, independently of website publication.

## 1. Publish the code

Commit and push this repository to your GitHub repository. The repository's
.gitignore excludes local credentials, virtual environments, databases and
hosting state. Do not upload server environment files or customer data.

## 2. Import into Vercel

Vercel → Add New → Project → Import the GitHub repository.

| Setting | Value |
|---|---|
| Root Directory | openclaw-project/platform/deploy/vercel |
| Framework Preset | Other |
| Build Command | node build.mjs (from vercel.json) |
| Install Command | Leave empty; no dependencies |
| Output Directory | Leave override disabled; Build Output API produces .vercel/output |

vercel.json runs the dependency-free build.mjs script. It produces Vercel Build
Output API routing before filesystem lookup, preserving Django account URLs.
The setup index is omitted when a backend is configured. Do not add vercel.mjs
or a second configuration file.
The first deployment shows the setup page. Note the stable production URL, for
example https://agentai-your-team.vercel.app. Git pushes redeploy the website;
they do not deploy Python code or restart services on the VPS.

## 3. Connect the existing VPS

A VPS HTTPS backend hostname is required (for example backend.yourdomain.com).
Point its DNS at the VPS and install a verified certificate. The current account
service is already installed privately on 127.0.0.1:18800. A separate TLS proxy
must forward only customer application routes to it. Do not expose /internal,
Gateway, control ports, database files or agent credentials.

The proxy must overwrite Host with the designated Vercel production hostname
and X-Forwarded-Proto=https. Overwrite X-AgentAI-Client-IP using the actual peer
address; never trust arbitrary client-supplied forwarding headers. Proxy peer
rate limits may be shared until the Vercel client-IP chain is verified.

On the VPS set AGENTAI_PUBLIC_ORIGIN to the exact stable production Vercel URL
in the private accounts.env file, then restart only agentai-platform-app.
Production previews do not automatically join the session/CSRF allowlist.

In Vercel → Project Settings → Environment Variables set:

BACKEND_ORIGIN=https://backend.yourdomain.com

Scope it to Production only, then redeploy. This value is a routing address,
not a credential. Invalid origins fail configuration rather than falling back
silently. Preview deployments without it retain the setup page. A configured
but unreachable backend produces an error; there is no mock login fallback.

## 4. Verify login before invitations

Check secure cookies, CSRF, recovery/activation links, logout/revocation,
no-store caching and direct two-account denial on the actual production URL.
Configure verified SMTP credentials only on the VPS. Host-only
manage.py onboard_trial --email <customer-email> creates a distinct account,
project, seven-day/$1 entitlement and onboarding mail job, up to two trials.
A separately enabled deliver_account_mail worker sends the activation code.
Customers choose their own passwords. Never put codes or mail credentials in Git.

## Current limitations

HTTPS backend hostname/certificate, Vercel project, stable origin, verified SMTP
and first invitation email still need configuration. The global queue and
account APIs are implemented; the native execution adapter is disabled, so
saved requests wait. This package is ready to publish a website, not to launch
paid autonomous agents. See ../../SERIAL_REQUESTS.md and
../../../plans/product/phase-06.md for progress and deployment evidence.

Local check: node check.mjs. Official documentation:
https://vercel.com/docs/git and
https://vercel.com/docs/build-output-api/configuration .

## Current production connection

Canonical website: https://getlumina.pro . www redirects to this address.
Backend: https://backend.getlumina.pro on the existing VPS, with Caddy
automatic HTTPS. Production BACKEND_ORIGIN is configured. The account service
uses AGENTAI_PUBLIC_ORIGIN=https://getlumina.pro. Customer-only proxy configuration
is in ../caddy/Caddyfile.getlumina. Owner Gateway and internal routes stay private.
SMTP/invitations and native execution are still pending.
