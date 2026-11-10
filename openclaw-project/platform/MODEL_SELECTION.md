# Model selection and saved API keys

Settings → Assistant → Models lists the host-owned Lumina catalog and up to 20
saved personal model/key/endpoint profiles. Only the existing main Lumina model
is offered by default. Adding a key tests it with the existing tiny probe, stores
it encrypted, and preserves the active choice. Selecting a profile or Lumina
applies to the next task without deleting keys or restarting the assistant.
Selection is account-wide across conversations. A saved key is paired with the
model and OpenAI-compatible endpoint tested when it was added; add a separate
profile to use another model with that key.

The UI gets the catalog from GET /v1/model-key. POST /v1/model-key/select accepts
an opaque id from that response. Save/remove/select reject accounts with waiting,
starting, running or uncertain work. The check and setting write share the same
SQLite IMMEDIATE transaction used by enqueue, with a second check after the
network probe. This prevents switching funding sources after task admission.
An active personal key bypasses Lumina’s model allowance as before; selecting
Lumina restores it. Browser decision calls remain billed/routed as before.

Customer cells use a stable `selection/selected` primary model at the native
relay’s /model/v1 endpoint. The host resolves the selected model for each call.
Personal calls use the selected decrypted customer key and the existing public
HTTPS/SSRF checks. Lumina calls use the cell credential at the existing fixed
10.77.0.1:4000 model proxy, preserving usage reporting and provider budgets.
The relay independently requires exactly one funded live request with matching
funding mode (the existing OWN_KEY_AMOUNT sentinel for personal tasks). Missing
or corrupt settings, a removed model, a failed personal key, disabled personal
access, admission mismatch and proxy errors fail visibly; they do not fall back
to a Lumina-funded call. Request sizes, streaming and concurrency remain bounded.
Provider capability limits still apply: entering a model id does not establish
that it supports every image, tool or context size; the existing probe checks a
small text request. Providers can reject unsupported requests visibly.

## Existing keys and persistence

Old account entries are read as the selected `key:legacy` profile. The first
edit wraps the existing ciphertext without re-encrypting it. Other accounts and
keys are preserved. New profiles remain AES-GCM encrypted with account-bound
keys and the existing keyring. Credentials are never returned to the UI or
placed in cell config. The settings file and atomic replacement are 0600 and
writers require the cross-process lock. Corrupt settings are refused without
overwriting the original. Retain the existing keyring when deploying.

## Adding Lumina models later

No frontend edit is required. Provision and price a model in the existing model
proxy first. Publish a host-managed JSON file, set AGENTAI_MODEL_CATALOG_FILE
for web, relay and supervisor services, and restart them. Example:

```json
{"models": [
  {"id": "lumina-default", "name": "Lumina", "model": "claude-sonnet-5-5"},
  {"id": "lumina-example", "name": "Example future model", "model": "proxy-model-id"}
]}
```

The second row is an example only, not an enabled model. Catalog entries must
contain exactly id/name/model; ids are stable and lumina-default is required.
Invalid catalog configuration exposes only the existing default. Removing an
actively selected catalog entry fails that selection rather than silently
choosing another provider. The supervisor model-key allowlist incorporates the
catalog at process startup. Refresh existing cell keys/config through the normal
supervisor path before admitting work on newly offered models. Keep catalog
publication and allowlist activation coordinated in the normal release window.

## Release and rollback

Deploy together with the pending location work. Quiesce admission and drain
existing tasks before replacing model routing. Back up model-keys.json and its
keyring using the normal private backup process. Release web, relay, UI and
supervisor; refresh/restart existing cells so their primary is selection/selected
before reopening admission. Existing warm cells still using old defaults must
not be left running after the change. No additional schema migration is needed
for model selection; the pending location migration is still required.

Verify a real Lumina task, two personal profiles, return to Lumina, and reported
usage on the deployed origin. Local tests use synthetic providers, not paid calls.

A binary-only rollback cannot read the new profile wrapper with old code. Stop
admission and preserve a private copy of the current settings before rollback.
If there have been no writes, restore the pre-release settings backup and prior
cell configs. If new profiles have been added, use a forward fix or convert each
account wrapper to its selected profile’s encrypted entry for the old format
(omit accounts selecting Lumina); retain the complete new-format file privately
so unselected profiles can be restored on upgrade. Do not discard those profiles
or rotate the encryption key as part of rollback.

## Verification

Frontend suite: 472 tests passed. Model/storage/HTTP/streaming/cell/location
regressions: 76 tests passed. Django model-key endpoint suite: 12 checks passed,
including account isolation, CSRF, spending-mode restoration and queued-work
rejection. Production build passed with existing bundle-size warnings.
`tests/model-selection-browser.mjs` exercises the built selector at 390/1440px
with synthetic keys. Both Chrome viewport checks passed: switching both directions,
preserving keys, busy rejection and horizontal overflow. No production deployment or paid model calls
were made.
