# Your own model (bring your own API key)

Settings → **Your own model** lets a customer point their assistant at any OpenAI-compatible endpoint with their own API key. While it is set, Lumina's spending limits do not apply to that account (they pay the provider directly); technical backstops still do.

## How it works

1. `POST /v1/model-key/save` (`accounts/model_key.py`): the endpoint address is parsed (`model_keys.parse_endpoint`: https only, public hostnames, port 443 or ≥1024, no credentials in the URL), then **probed** with one tiny `/chat/completions` request, then stored encrypted (`ModelKeyStore`, AES-256-GCM, key derived from the app `SECRET_KEY` or `AGENTAI_MODEL_KEY_FILE`). The key is never returned again, only its last four characters.
2. At the next cell start `CellProvisioner.before_start` reads the store (`own_model_reader`) and writes a `byok` provider into the assistant's config, whose base URL is the tool relay's `/byok/v1` and whose API key is the cell's own relay token. The customer's key is **not** in the cell.
3. The assistant calls the tool relay (`agentai_platform/tool_relay.py`, `/byok/v1/chat/completions`, `/byok/v1/models`). `ModelRelay` identifies the cell, looks up the account's key, **re-resolves DNS and connects to a checked public IP** (all addresses must be public, TLS verified against the name, no redirects), forces the customer's model name and streams the answer back.
4. `accounts/chat.py` `own_key_active()` makes chat sends `unmetered`: a nominal 1 µUSD reservation (needed by the browser tool's ownership check) with task/daily/period allowances skipped (`BudgetLedger.admit(unmetered=True)`).

## Switching between your own model and Lumina's

Settings → Your own model shows **Lumina's models / My own model** once a key is saved (`POST /v1/model-key/use` with `{"use": "own" | "lumina"}`). Choosing Lumina's models keeps the key saved, so switching back needs no re-entry. Two stored, non-secret flags per account decide everything (`model_keys.py`):

* `use_own`: what the customer chose. Saving a key sets it. An entry from before the switch existed reads as on.
* `applied`: the assistant has been **seen running** on the customer's model. Any real change of `use_own` clears it; the relay sets it again on the first `/byok/v1/chat/completions` call made while `use_own` is true. An entry from before the switch reads as applied.

Every part reads the same flags, so they cannot disagree:

* **Cell config** (`own_model_reader`): the `byok` provider is written only when `use_own` is true, at the next cell start. That is the only moment the assistant changes model.
* **Spending limits** (`accounts/chat.py` `own_key_active()` -> `model_keys.unmetered`): skipped only when `use_own` AND `applied`. After switching to own, the assistant still answers with Lumina's models until its cell restarts, and Lumina pays for those, so limits stay on until the relay sees it calling. After switching to Lumina's, the limits come back at once.
* **Relay**: keeps answering while a key is saved, whatever `use_own` says, so an assistant that has not restarted yet does not fail. It never marks `applied` once the customer has chosen Lumina's.

## Backstops (technical, not spend)

120 requests/min and 6 simultaneous per account; 32 MB request size; connect/read time limits; only JSON or event-stream replies relayed; the queue limit still applies.

## Switches

* `own_model_keys` in `/var/lib/agentai-platform/own-model-keys.json` (owned by `agentai-platform`; the web app and tool relay run as that user and cannot read `/etc/agentai-supervisor`): `true` = everyone, a list of account ids = those accounts, anything else = nobody. This is the kill switch: set it to `false` and the relay refuses, `own_key_active()` becomes false, and cells fall back to Lumina's models at next start.
* **Do not enable it before the published privacy policy describes it** (`platform/privacy/README.md`).

## Known limits

* Changing, switching or removing a key applies the next time the assistant's cell starts (an idle cell stops after 45 minutes). Until then an assistant that was on the key keeps using it; after *removing* the key it gets a "no key" error from the relay until it restarts.
* The browser's step decider (TypeSafe JEV) never uses a customer's key.
* The save request blocks one web worker while it probes (up to ~22 s worst case).
* Rotating the app `SECRET_KEY` without a key file makes stored keys unreadable (customers must re-enter them). Set `AGENTAI_MODEL_KEY_FILE` to avoid this.
* Tests: `tests/test_model_keys.py`, `tests/test_byok_http.py`, `tests/test_cell_config.py`, `tests/test_budget.py`, `tests/test_chat.py`, `accounts/test_model_key.py`, `lumina/src/components/OwnModel.test.tsx`. The switch: `StoreChecks`/`RelayChecks` in `tests/test_model_keys.py`, `tests/test_cell_config.py`, the `use` tests in `accounts/test_model_key.py`.
