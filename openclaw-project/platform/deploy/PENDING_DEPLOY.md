# Read before the next deploy (written 2026-11-14, corrected the same day)

The server runs `e16ffe7` (13 November). `main` is ahead by PRs #36, #37, #38 and, once merged, #39 and the roadmap Phase 0-1 pull request.

## Why automatic deploys are refused, and the one-time fix

The installed deploy program on the server is the 1 November version. It never clears the record of hand-released files, so every commit since looks like it would undo a
manual release (exit 30). The repository's version clears the record after a deploy and, from the Phase 0-1 pull request on, keeps its installed copy up to date by itself.

Do this once, as root on the server, after merging:

```sh
# 1. install the current deploy program (from the merged commit; here taken from a checkout on your machine)
scp openclaw-project/platform/deploy/agentai-deploy lumina:/usr/local/sbin/agentai-deploy.new
ssh lumina 'python3 -m py_compile /usr/local/sbin/agentai-deploy.new && install -o root -g root -m 0755 /usr/local/sbin/agentai-deploy.new /usr/local/sbin/agentai-deploy && rm /usr/local/sbin/agentai-deploy.new'
```

2. GitHub → Actions → **Deploy to server** → Run workflow on `main` with **Dry run unticked** and **Overwrite manual changes ticked**. (The form defaults to a dry run, which
   reports success and changes nothing: that is what happened on 14 November.)
3. Check: `ssh lumina 'cat /var/lib/agentai-deploy/last'` equals `git rev-parse origin/main`. From then on a merge to `main` deploys by itself.

## After that deploy

1. **Supervisor process.** The deploy updates the supervisor tree and restarts the lifecycle worker, bridge, relay, browse service and request worker. The supervisor process
   itself (`agentai-supervisor-native`) is not restarted. It needs one restart to load the new key code (keys with no expiry and no budget, repaired before each cell start):
   `systemctl restart agentai-supervisor-native` at a moment when no cell is being started or stopped.
2. **Server LiteLLM config** (`/opt/openclaw-production/config/litellm.yaml`, hand-managed): remove the two lines of the `index: -1` cache injection point so it matches
   `openclaw-project/deploy/litellm.yaml`, then `docker restart openclaw-production-litellm-1`. The end-of-conversation cache point is set by the model relay
   (`mark_cache_points`), which this deploy brings to the server for the first time. Measured on the live logs, the old point cost 58% of all model spend.
3. **Timing marks:** add `Environment=AGENTAI_TIMING=1` to `agentai-request-worker`, `agentai-platform-app`, `agentai-cell-bridge` and `agentai-lifecycle-worker`
   (a drop-in each), `systemctl daemon-reload`, restart them. After a week: `python3 deploy/latency_report.py`.
4. **Migrations 0037, 0038, 0039** are additive and applied by the release step. No data changes: every account starts with no spending limit.

Already done: the live assistant key's expiry and lifetime budget were removed by hand on 14 November.

Delete this file once everything above is verified.
