# Read before the next deploy (written 2026-11-14)

These are merged in code but need a step on the server that the automatic deploy does not do.

1. **The supervisor release must go out too, not only the app.** `agentai_platform/lifecycle/secrets_custody.py` and `cell_config.py` changed: assistant model keys
   are issued with no budget and no expiry, and an existing key is brought up to date before every cell start (`ensure_unlimited`). The automatic deploy covers the
   app and the web UI; the supervisor code under `/opt/agentai-supervisor` is released by hand.
2. **The live assistant key expires on 2026-11-16** (issued 2026-10-12 with a 35-day life and a lifetime budget). Until the supervisor release above has started
   the cell once, lift it by hand: LiteLLM `POST /key/update` with `{"key": <the key>, "duration": "-1", "max_budget": null, "tpm_limit": 4000000, "rpm_limit": 120}`.
3. **Server LiteLLM config** (`/opt/openclaw-production/config/litellm.yaml`, hand-managed): remove the `index: -1` cache injection point so it matches
   `deploy/litellm.yaml`, then restart the LiteLLM container. The end-of-conversation cache point is set by the model relay (`mark_cache_points`), which this
   deploy brings to the server for the first time; measured on the live logs, the old point cost 58% of all model spend.
4. **Migration `0037_spend_limits.sql`** is additive and applied by the normal release step. No data is changed: every account starts with no limit.
5. **Request worker** now waits 1 second when idle (was 3) and reports failures with code locations; no unit file change is needed.

Delete this file once all five are done.
