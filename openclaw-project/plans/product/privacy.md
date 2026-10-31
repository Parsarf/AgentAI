# Privacy and data-leak protections (Lumina)

Policy (owner, 2026-10-13): no new restrictions on what the assistant may do. Security effort goes only into stopping data leaks and protecting each customer's privacy.

## Isolation between customers (verified from configuration)
- Each assistant is its own gVisor container, non-root, no extra privileges, own network and own volume (`/var/lib/agentai-fleet/.openclaw/fleet/cells/<tenant>`, mode 0700), own provider key and budget.
- Host firewall (`agentai_cells` nftables): cells cannot reach other cells, the host's services, private ranges or cloud metadata. The only host door is the model relay (10.77.0.1:4000). Browser stages sit in the same firewall.
- **Model relay is now HTTP-aware** (`deploy/model-proxy/agentai_model_proxy.py`): only chat completions and the model list pass. Every LiteLLM management route (keys, users, teams, spend logs, config) is refused before it reaches LiteLLM, so a customer key cannot read others' usage or mint keys. Tested for traversal, encoding and request-smuggling shapes. Rollback: restore `agentai_model_proxy.py.bak` and restart `agentai-model-proxy`.
- Every account API read is scoped by account; downloads use single-use tickets; the cell bridge reads only the calling account's workspace without following symlinks.

## What leaves the server
- Model provider (Anthropic via LiteLLM): prompts must go there to work. LiteLLM stores no message content (`turn_off_message_logging: true`). Owner action: request zero-data-retention on the Anthropic account if available.
- Web search (Brave, owner key): search queries leave the host. They carry no customer identity, only the key.
- TypeSafe/JEV: **chat routing is switched OFF** (it only measured, with no customer benefit). Browser JEV still sees page text and element labels in shadow mode; both are now passed through `privacy.scrub` (emails, phones, card/ID/IBAN numbers, addresses, IPs, URL credentials, tokens removed) before sending.
- App logs record route and status only, never message content.

## Retention
- Browser screenshots (may show personal pages) are deleted 24 hours after a task, on every task end and at service start.
- Task events 30 days, chat 90 days (plan limits); backups encrypted (age) and expire at 30 days.

## Still open
- Off-server backup destination (encrypted copy off the VPS).
- Dedicated Brave key per environment.
- Per-key `allowed_routes` in LiteLLM as a second layer (needs a throwaway-key test; not required now that the relay filters routes).
- Operator access: the owner can read the database on the server; keep the server login to key-only and do not share it.
