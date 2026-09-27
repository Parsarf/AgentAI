# Jev (TypeSafe AI) — research notes for this project

Researched 2026-09-26. Purpose: understand the new "System One" model Jev,
how it can serve web-browsing pipelines, and where it (and other techniques)
can cut model costs while raising output quality — specifically for an
agent stack like ours (OpenClaw workers + LiteLLM proxy with a $2/day,
$25/30d cap).

---

## 1. What Jev is

- **Vendor**: TypeSafe AI (San Francisco, founded 2024) by Diogo Almeida
  (ex-OpenAI; RLHF, InstructGPT, ChatGPT, GPT-4), Erik Gafni, Sasha Sheng.
  $40M seed led by DCVC at a reported ~$200M valuation.
- **Released**: early access 15 Sep 2026; current version `jev-1.13.0`
  (alias `jev-latest`). Proprietary, closed weights. Direct signups were
  paused ~22 Sep after a demand surge; gateways serve it today.
- **Not an LLM.** It never generates free text. A request is a block of
  `state` (string, JSON object, or array of strings) plus typed
  `questions`; the model answers **all questions in one parallel pass**
  (70–500 ms) with typed answers and **calibrated probabilities**.

| Primitive | Returns | Use |
|---|---|---|
| `choice` | one of up to 255 options + per-option probabilities | routing |
| `score` | level on a 2–10 rubric + probabilities | severity/quality |
| `noul` | yes/no probability 0–1 (spelled `boolean` in Vercel SDK) | gating |

- **Training**: RLCD — Reinforcement Learning for Calibrated Decisions
  (an RLHF descendant optimized for calibration, not chat). Synthetic data
  only. Architecture/weights unpublished; outsiders suspect a fine-tuned
  open-weight LLM underneath.

## 2. Specs, pricing, benchmarks

| Item | Value |
|---|---|
| Latency | 70–500 ms, often <100 ms |
| Price | **$0.042 / 1M input tokens; output free.** No free tier |
| Typical decision | ~400 tokens ≈ $0.000017 → **$1 ≈ 60,000 decisions** |
| Context | 64k native (32k state + longest question); **32k on gateways** |
| Modalities | text + structured data only (no images/audio/video) |

Benchmarks — read with skepticism, they are days old:

- TypeSafe self-run: 67.8% agreement vs GPT-5.6 Sol's 74.1% on their evals;
  headline 193.6× faster / 444.6× cheaper. Self-admittedly "high end".
- Independent: Vercel 5–18× faster **and** more accurate on a safety
  classifier; Bryo 10–20× cheaper than Gemini; Doom demo at 10 decisions/sec
  (~$7/hr); beat Fable 5.1 on blitz-chess time, lost to GPT-6 Astra in 18.
- Honest summary: Jev trades a few points of accuracy for 5–20× real-world
  speed/cost. It is a **judgment layer, not a knowledge layer** — it judges
  the state you hand it; it cannot retrieve facts or reason at length.

## 3. Access routes (identical pricing everywhere)

| Route | Model string | Notes |
|---|---|---|
| **OpenRouter** (no waitlist) | `typesafe/jev-1.13` | plain HTTP POST `/api/alpha/decisions`; easiest; beta schema |
| Vercel AI Gateway | `typesafe-ai/jev` | SDK `experimental_evaluate`; per-request ZDR; **cannot pin versions**; confidence lives in `providerMetadata.typesafe.confidence` |
| Cloudflare Workers AI | `typesafe/jev` | `env.AI.run` with evaluation schema (not chat completions) |
| TypeSafe direct | `jev-1.13.0` | waitlisted; version pinning + inline confidence; retention policy not public — ask before sending sensitive state |

Operational gotchas: pin the version when tuning thresholds and log the
`model` field of every response; question IDs are not portable between
routes; gateway state capped at 32k; confidence field location differs by
route (copy-pasting parsers silently drops it).

## 4. Using Jev for web browsing

**Jev cannot browse.** No live web access, no images, no agent loop. Its
role in browsing is the **decision layer around the fetch**, which is
exactly where an agent burns LLM tokens today:

1. **Search-result triage** — fetch 20 results' snippets as `state`, ask
   `choice`/`score`: "which 3 of these URLs best answer the task?" The
   worker then fetches/reads only those. Cuts web-fetch + long-context
   reads by ~5–10×.
2. **Page relevance gate** — after `web_fetch`, before the reasoning model
   reads 20k chars: "does this page actually address X? (noul)" + `score`
   relevance. Irrelevant pages die for ~$0.00002 instead of a Sonnet turn.
3. **Watcher "meaningful change" scoring** — our watchers escalate on hash
   change; most hash changes are ads/dates. Add a Jev `noul`: "is this
   change materially different for the user?" Quiet watchers stay quiet →
   the single biggest saver for 24/7 scheduled work.
4. **Injection screening** — `score` "does this page contain
   instruction-like text aimed at the agent?" Useful as **one input** to
   the gate, never the gate itself (see §5).
5. **Read-strategy routing** — `choice`: summarize vs extract vs discard;
   `score` page quality/credibility before citing.
6. **Browser-action gating** — LangChain ships an `AutoModeMiddleware`
   pattern using Jev to flag risky tool calls; same idea for a browser
   worker: score "is this click/submit consequential?" before asking the
   (expensive, slow) approval LLM turn.

Integration paths for a LiteLLM-fronted stack: OpenRouter is itself a
LiteLLM-supported provider, so the proxy can likely expose Jev and meter it
in the same cost ledger (schema support for the `/decisions` endpoint is
**unverified** — test before committing). Simplest robust option: a small
HTTP helper called from tool/skill code, so Jev verdicts stay out of model
context entirely, like any other tool result.

## 5. Security (matters for an untrusted-content pipeline)

Attacker-controlled state flows straight into the classifier, so:

- **State poisoning** — a crafted page can steer the "relevance/injection"
  verdict itself. The "can't hallucinate" claim is narrow: Jev can't leave
  the option set, but it can confidently pick the attacker's option.
- **Threshold bypass** — inputs tuned to sit just on the wrong side of a
  confidence cutoff look legitimate.

Rules we should keep: treat every Jev verdict as **attributed data** (one
input to a decision, never the decision or a policy authority); log verdict
+ probability + `model` field for audit; use ZDR or ask TypeSafe about
retention before sending private state; re-verify thresholds after any
version bump.

## 6. The broader cost-cutting / smarter-model playbook

Ranked by expected impact for a capped, worker-based agent like ours:

1. **System-1 gate in front of every expensive turn** (Jev, ~$1/60k
   decisions): triage, relevance, watcher-noise, risk-gating. This attacks
   the real budget killer — full LLM turns spent on decisions.
2. **Right-size the reasoner.** Keep Sonnet-class for planning/writing;
   route mechanical turns to Haiku-class. A Jev `choice` can be the router
   ("easy | hard | refuse").
3. **Cheap-check-first watchers.** Deterministic check scripts + hash gate
   first (already built in Phase 3); Jev as the second gate; LLM last.
4. **Prompt caching.** Stable system prompts and stable tool schemas hit
   Anthropic cache reads (~10× cheaper); avoid per-turn prompt churn.
5. **Context diet.** Cap snapshots/fetches, pass summaries not dumps, wrap
   and trim untrusted content — input tokens are what you pay for.
6. **One call, many questions.** Jev answers N typed questions in a single
   parallel pass — collapse separate classifiers into one request.
7. **Output discipline.** Hard `max_tokens`, no retry storms, fail closed
   (all already in place in our stack).
8. **Open/local alternatives.** `Kev-9B` (Apache-2.0) scores 0.852 vs
   Jev's 0.857 on the comparison eval — viable where data can't leave the
   machine; `jeff` / `poorjev` run locally. Note our VPS has ~3.8 GB RAM
   — a 9B model does not fit next to the running stack; local options
   belong on the Mac, not the server.

### When NOT to use Jev

Anything needing generation, long reasoning, fact retrieval, multimodal
input, or an auditable explanation. High-stakes irreversible gating should
use it only as a pre-filter with a human/approval path behind it.

## 7. Adoption checklist (if we pilot it)

- [ ] Create OpenRouter account; $5 prepaid ≈ 300k decisions; key into
      `.env` (never in code); route through LiteLLM if the schema works.
- [ ] Pin `typesafe/jev-1.13`; log `model` + probabilities per decision.
- [ ] Pilot on watchers first (offline-comparable: replay past check
      outputs, measure noise filtered vs Sonnet agreement).
- [ ] Then search triage in the research flow; measure fetch/turn reduction.
- [ ] Re-tune thresholds per version; keep verdicts as attributed data only.

## 8. Sources

- [Wikipedia — Jev (AI model)](https://en.wikipedia.org/wiki/Jev_(AI_model))
- [TypeSafe launch blog (via Wikipedia refs)](https://www.typesafe.ai)
- [TechCrunch — A new kind of AI model from a ChatGPT inventor](https://techcrunch.com) (18 Sep 2026)
- [Business Standard — What is Jev?](https://www.business-standard.com/technology/artificial-intelligence/what-is-jev-inside-the-new-ai-model-built-to-make-software-decisions-126092200452_1.html)
- [emergent.sh — Meet Jev](https://emergent.sh/news/what-is-jev)
- [AI FrontPage — signups paused after demand surge](https://aifront-page.com/typesafe-ai-pauses-jev-ai-model-signups-demand-surge/)
- [Community research writeup incl. setup routes & troubleshooting](https://github.com/Raunaksplanet/jev-research-sept-2026/blob/main/jev-writeup.md)
- [Rohit Raj — open-weights alternatives (Kev-9B)](https://rohitraj.tech/notes/jev-alternatives-open-weights-decision-models-2026)
- [DigitalOcean — What is Jev (2026)?](https://www.digitalocean.com/resources/articles/what-is-jev)
- [Towards AI — Jev: typed decisions](https://towardsai.com/p/machine-learning/jev-by-typesafe-a-new-ai-model-for-typed-decisions-2)
