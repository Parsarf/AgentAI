# Phase4 disposable-cell verification evidence

Owner authorized two actions: re-issuing the pending account activation and one
disposable native cell exercise against the isolated candidate CLI.

Invitation: the expired onboarding token was invalidated and a fresh activation
mail was delivered through the Gmail SMTP pipeline (delivered=True). The
account_admin invite path was correctly blocked by the unique-email constraint
because the owner user row already exists; nothing changed on that path.

Disposable cell (isolated HOME, pinned 2026.9.6 candidate, already-local
pinned image): create --no-start → list `created` → start → `running` → stop →
`exited` → backup (gzip archive) → rm → registry empty, tenant string absent.
Measured cell peak 245.1 MiB under the 512 MiB cap; host kept ~460 MiB
available with the cell up. No model/provider call happened inside the cell;
no customer, owner or payment effect occurred; everything was deleted and the
owner stack verified healthy afterwards.

Facts now load-bearing for the driver: start/stop/rm emit text only (registry
is the only state source); create prints the cell Gateway token in plaintext
on stdout (kept in a private temp file, never parsed or stored); backup
archives are credentials; fs-safe temp-workspace admission rejects workspaces
whose ancestry includes a directory owned by neither the effective uid nor
root — this image shipped `/` owned by an orphaned uid 501, so every dispatch
was refused until `/` was corrected to the standard root:root (reversible,
non-recursive).

Host fixes: chown root:root / (reversible via chown 501 /); unprivileged
system user agentai-fleet (uid 1000, docker group) retained as the runtime
identity candidate. Driver v2 shipped with registry-proven receipts and the
observed custody example. Phase 4 remains PARTIAL; Phase 15 NOT_RUN; no native
backend is enabled in the shipped entry point.
