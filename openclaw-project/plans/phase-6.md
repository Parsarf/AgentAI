# Phase 6 — personal integrations, lean implementation

Owner authorized advancement on2026-09-27 with heavy/paid acceptance tests
deferred and earlier gates unpassed. Required services: Gmail, Calendar,
Drive, and selected GitHub repositories. Google account supplied privately
in runtime configuration; GitHub repository selection still required.
No scope is silently excluded. Gate6 cannot pass from setup alone.

Owner clarified later: account setup will be done later; current deliverable
is an extensible base with an easy way to connect tools. `bin/connect-tool`
and the installed VPS manager wrap native MCP operations and add a restricted
reader namespace automatically. They support HTTPS/stdio adapters, exact
selected tools, protected native OAuth/profile binding and disabled registration.
No custom adapter, router, scheduler or approval engine is created. Current
base delivery is complete independently of deferred full Gate6 acceptance.

## Decisions and implementation

- Use native `mcp.servers` and native layered tool policy. Bundled gog/github
  skills exist, but their CLI binaries and account authorization are absent
  on the VPS. Those skills expose broad CLI procedures and do not enforce
  connector write approval. No arbitrary worker shell access added.
- Google: maintained `workspace-mcp==1.29.0`, isolated non-root Docker stdio
  process, only Gmail/Calendar/Drive, `--read-only`, explicit native tool
  inclusion. Python base resolved to a digest at build; resulting image ID
  and full installed dependency freeze retained. Provider SDK egress needs
  network; container has no Gateway state, Docker socket or worker workspace.
- Credentials: dedicated0700 host directory mounted only into Google
  connector; client-secret.json and refresh tokens remain outside git/model
  context. New connector remains disabled until client setup and owner login.
- GitHub: official hosted `/mcp/readonly` endpoint, exact read tool list;
  selected-repository fine-grained credential preferred over account-wide
  OAuth. No credential present yet. OAuth discovery compatibility is not
  assumed; auth mechanism is finalized after repository selection.
- Researcher is the only eligible content reader. Add the two connector
  namespaces to global/sandbox ceilings and researcher restrictive allow;
  coding profile registers native MCP, while existing deny rules prohibit
  shell, sends, spawning, scheduling, policy and owner memory. Other agents
  deny `bundle-mcp` and both namespaces; native Codex projection is scoped
  to researcher only, excluding builder/debugger.
- Drafts are local proposals, not provider drafts. Gmail compose scope also
  grants send permission; omit it and all provider write tools in this increment.
  No second approval system, automatic inbox watcher, new cron or budget change.

## Permission matrix

| Service | Credential scopes/permissions needed | Reader and operations | Writes | Authentication/storage/revocation |
|---|---|---|---|---|
| Gmail | `https://www.googleapis.com/auth/gmail.readonly`, identity scopes requested by installed connector | researcher: bounded search/content | No send, delete, label changes or provider draft tool; local draft only | Owner Google consent; protected connector client/token files; revoke Google app consent and remove only that account's tokens |
| Calendar | `https://www.googleapis.com/auth/calendar.readonly`, identity scopes | researcher: calendar list and today's events in America/Los_Angeles | No event creation, updates, invites or deletion | Same Google protected connection; reconnect on expiry/revocation |
| Drive | `https://www.googleapis.com/auth/drive.readonly`, identity scopes | researcher: selected item search/content/list | No upload, share, permission change or deletion | Same connection; readonly permits reading all accessible Drive items, not merely the selected demonstration item |
| GitHub | Selected-repository fine-grained token: metadata/read, contents/read, issues/read, pull requests/read; identity endpoint compatibility to confirm | researcher: files, commits, branches, issues and PR reads | No branch creation, comments, push, merge or delete | Protected native auth-profile bearer binding; expiry/revoke at GitHub settings; not yet connected |

Upstream base identity scopes are `openid`, `userinfo.email`, and
`userinfo.profile` (the latter two use the Google API scope URL prefix).
Effective granted scopes still require consent/readback before activation;
no provider-identity claim now.
Installed MCP headers/env accept primitive values, not SecretRef objects.
Use the supported `auth: oauth` plus `oauth.authProfileId` bearer mapping to
protected native auth state after verifying token/profile compatibility; do
not invent a header SecretRef or place a literal PAT in tracked configuration.
Native Codex `prompt` metadata is defense in depth only; it does not prove an
arbitrary built-in connector write is approval-gated. Reads only enforced by
connector mode/tool omission; effective runtime fixtures deferred.

## Lightweight checks and remaining work

Run only installed CLI/help checks, config schema/dry-run, exact authored
readback, dependency/version capture and source syntax/whitespace checks.
No inference, mail reads, provider drafts, negative fixtures, revocation,
restore, browser/sign-in automation or paid acceptance suite.

Google account identity, OAuth client credentials and consent are prerequisites
to live connection, not test failures discoverable through normal use. GitHub
repository selection and narrow credential likewise required. After sign-in,
one lightweight provider identity/readback and scope check should establish the
connected account before normal use; heavier acceptance remains deferred.

Rollback only the recorded authored config fields and appended Phase6 note
sections, preserving subsequent edits. Disable/remove this phase's connector
names; retain existing credentials, jobs and unrelated data. Private backup,
image IDs, readbacks and precise run results belong in the evidence manifest.

## Documentation checked

- https://docs.openclaw.ai/tools/mcp
- Installed `/app/docs/cli/mcp/registry.md` and `transports.md`
- https://github.com/taylorwilsdon/google_workspace_mcp/tree/v1.29.0
- https://github.com/taylorwilsdon/google_workspace_mcp/blob/v1.29.0/auth/scopes.py
- https://github.com/github/github-mcp-server/blob/main/docs/remote-server.md

No activation or useful live provider result is claimed by this plan.
