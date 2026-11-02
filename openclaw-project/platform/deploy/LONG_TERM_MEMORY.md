# Long-term memory (Hindsight)

The assistant can remember short preferences and facts a customer told it, and use them in later conversations. Each customer has their own private store; the customer sees and deletes every note in **Settings → Memory**. **Off for everyone until the owner turns it on.** Code: `agentai_platform/longterm_memory.py`, `accounts/longterm.py`. Tests: `tests/test_longterm_memory.py`, `accounts/test_longterm.py`, `lumina/src/components/MemoryNotes.test.tsx`.

## How it works

```
customer cell ──MCP──▶ tool relay ──▶ LongTermMemory ──▶ ledger (Lumina DB: longterm_memories)
 (2 tools)             (knows the account)             └─▶ Hindsight (bank per account)
```

* **Two tools** reach the assistant through the existing authenticated tool relay: `lumina_memory_recall(query)` and `lumina_memory_remember(content, kind)`. Neither has an account, bank or index argument; extra arguments are refused. They exist for an account only while the owner's switch is on (asked on every call).
* **The account comes from the relay**, which identifies the cell by its own credential. **The bank id is `lumina-` + a keyed hash of the account id**, computed on the server with a secret the cell never sees. A cell can neither name nor guess another customer's bank, and holds no index address or credential.
* **The ledger is the source of truth.** The text lives in `longterm_memories` so the customer can list and delete it, so deleting never depends on the index being up, and so the index can be rebuilt (`memory_sweep --reindex-account`). The index needs no backup of its own.
* **Hindsight only indexes.** Banks are created with `retain_extraction_mode=chunks` (each note stored exactly as written, **no language model is called on notes**) and `enable_observations=false` (nothing is synthesised from notes). So the index holds only the note and its embedding, and deleting the document (`DELETE /v1/default/banks/{bank}/documents/{id}`, which the API documents as cascading to its memory units and links) removes everything.
* **Deleting**: the text is blanked in the ledger and the entry disappears from the customer's list at once; then the document is removed from the index. If the index cannot confirm, the row stays `deleting` and `memory_sweep` retries. "Delete everything" removes the whole bank.
* **Recall output is data, not instructions**: marked as such, bounded (6 results, 600 characters each), control characters stripped. The tool description tells the assistant to save only what the customer said (never web, file or tool text), and secrets (keys, tokens, card numbers, "password is …") are refused in code.
* **Backups**: `longterm_memories` is classified `LIVE` in `ops/restore.py`: a restore never brings a deleted note back. Encrypted database backups can hold a note for up to 30 days after deletion (the policy says so).
* **Own model keys**: memory never uses a customer's own model key; it calls no model at all.

## Deploy Hindsight (requirements, not a recipe)

Hindsight (MIT, Vectorize) is run **on the same server or private network as the platform**, reachable only from the app user (the tool relay and the web app).

1. **Network**: bind to loopback or a private address; plain `http://` is accepted only for loopback/private/single-label hosts (`parse_base_url`). Nothing public.
2. **API key**: enable Hindsight's API-key auth; put the key in a file `0600` owned by the app user and set `AGENTAI_HINDSIGHT_KEY_FILE`. The client sends `Authorization: Bearer <key>` (format confirmed in the deployment's own `/openapi.json` before enabling; adjust `HindsightClient._call` if it differs).
3. **No outside model sees notes**: with `chunks` and observations off, Hindsight's retain path calls no LLM. Run embeddings and the reranker **locally** (Hindsight's local/TEI options), not an external embeddings API. If the server insists on an LLM setting to start, give it the provider already in `litellm.yaml` and nothing else; adding any other provider is a privacy-policy change (see `privacy/README.md`).
4. **Logs**: Hindsight keeps audit logs and LLM request logs (`/audit-logs`, `/llm-requests`). Make sure no note text ends up in files kept longer than the policy's 7-day log promise.
5. **Postgres**: Hindsight's own database holds the index. It may be rebuilt from the ledger, so it does not need to be in the encrypted backups; if you do back it up, deleted notes then persist there too and the policy's 30-day statement must cover it.

## Settings (all in `accounts/settings.py`, from the environment)

| Variable | Meaning |
|---|---|
| `AGENTAI_HINDSIGHT_URL` | Base address of the Hindsight server, e.g. `http://127.0.0.1:8888`. Empty = feature unavailable. |
| `AGENTAI_HINDSIGHT_KEY_FILE` | Bearer key file (private, regular file, not a symlink). Optional only if the server needs no key. |
| `AGENTAI_HINDSIGHT_BANK_SECRET_FILE` | **Dedicated** secret (16+ characters, private file) for bank ids. Never derived from `SECRET_KEY`. **Do not lose or change it**: bank ids derive from it; after a change run `memory_sweep --reindex-account` for every account and delete the old banks. Empty = feature unavailable. |
| `AGENTAI_LTM_SWITCH_FILE` | Default `/var/lib/agentai-platform/long-term-memory.json`. |

Fails closed: no switch, no URL, no readable secret file, or a group/world-readable secret file = the tools do not exist and Settings shows nothing. Entries already stored are kept.

## Turning it on

**First publish the privacy policy** (it is already updated in the repo, `deploy/vercel/public/privacy.html`, with `privacy/facts.json`; publishing it is a separate step, see `privacy/README.md`). Then, as the app-owning user:

```sh
echo '{"long_term_memory": ["<owner account id>"]}' > /var/lib/agentai-platform/long-term-memory.json   # one account first; true = everyone
```

It is read on every request. Setting it to `false` withdraws the tools at once and keeps the entries. The tool relay must be restarted once after the settings above are first set (the tools are registered at start), and a customer's cell may need to restart before it lists the new tools (runtimes can cache the tool list).

## Operations

```sh
python manage.py memory_sweep                          # retry unconfirmed deletions, clean half-finished saves; run from a timer every few minutes
python manage.py memory_sweep --erase-account <id>     # remove everything for one account (run when an account is deleted)
python manage.py memory_sweep --reindex-account <id>   # rebuild one account's index from the ledger
```

Schedule the first command. Until it is scheduled, a deletion the index could not confirm stays pending (the note is already gone from the customer's list and from Lumina's database).

## What has and has not been verified

**Unit and HTTP tests** (`tests/test_longterm_memory.py`, `accounts/test_longterm.py`, `lumina/src/components/MemoryNotes.test.tsx`; an in-memory Hindsight stand-in follows the exact HTTP calls): per-account isolation of every call, bank ids, switch, tool schema, secret refusal, saves that fail halfway, deletes with the index down and the sweep, delete-all, reindex, restart persistence, HTTP views, restore classification, privacy record, OpenAPI spec.

**Against Hindsight's published OpenAPI spec (v1.1.0)**: every path and field used, the document delete cascade, the `chunks` mode ("stores each chunk verbatim and never calls an LLM").

**Against a real server, 2026-11-01** (`hindsight-api` 1.1.0 from PyPI, `HINDSIGHT_API_LLM_PROVIDER=none`, `ApiKeyTenantExtension`, local embeddings, embedded Postgres, loopback only; `tests/live_hindsight.py`): banks get `retain_extraction_mode=chunks` and `enable_observations=false`; a differently worded question finds a note by meaning; one account's bank never returned another account's notes in either direction; `Authorization: Bearer <key>` is the right format (wrong key = 401); after `forget` the bank holds 0 memory units and 0 documents; `forget_all` removes the bank (404 afterwards); `reindex` rebuilds from the ledger and does not bring deleted notes back; the server log showed no language-model calls.

Re-run it any time against a staging or production-like server:

```sh
AGENTAI_LIVE_HINDSIGHT_URL=http://127.0.0.1:8888 AGENTAI_LIVE_HINDSIGHT_KEY=... python -m unittest tests.live_hindsight
```

**Still to check on the real deployment before enabling for customers:**
1. Run `tests/live_hindsight.py` against the actual server (not the throwaway one).
2. Embeddings and the reranker run locally, and the server makes no outbound calls while serving. The first start downloads the embedding and reranker models from a public model hub, so pre-download them (or run the server once with network access) and then confirm it works with outbound traffic blocked.
3. **Recall always returns the nearest notes, even unrelated ones** (an account asking about seats got its own peanut allergy back). That is not a leak (it is the same account's own note), but it is noise for the assistant. If it matters, filter with `min_scores` in the recall request once a good cutoff is measured on real notes.
4. Hindsight's own audit and request logs must not keep note text longer than the policy's log retention.
5. Production Postgres (not the embedded development one) and the Hindsight process under its own service user.
