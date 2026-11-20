# Roadmap Phase 4 - customer knowledge

**Status (2026-11-19): PASS.** Every feature is built, deployed (`b0a5dd7`, read back from `/var/lib/agentai-deploy/last`, equal to `origin/main`), installed on the host and
**on for every account** (`customer_uploads`, `customer_knowledge`); all four exit gates passed on the live stack with `deploy/phase45_live.py`, and the policy that describes
uploads, the parsed text and the index is published.

## What passed (live)

Run on the server with two disposable accounts that the script makes and offboards (`deploy/phase45_live.py`, logs `/root/phase45_live-20261119{c,d}.log`; run `d` after the embedding server was resized, with 0 restarts). Model spend of
all proofs on 2026-11-19: a few vision reads of invented pages, well under $1 (budget $10).

| Gate | Result |
|---|---|
| **1. The knowledge evaluation set passes** with the sealed reader, the self-hosted embedding model and PostgreSQL | `P4-EVAL` PASS: 22 documents, 42 questions: recall@5 **0.952**, recall@10 **0.976**, top-1 0.81 to 0.83, citations **1.0**; table cells **116 of 116**; comparison (changed number, changed notice, moved clause) all found; the planted conflict reported (1 of 1); planted unsupported claims flagged **4 of 4**, none wrong; search median 72 ms. `P4-SCAN` PASS: a page that is only a picture is read by the vision model (1 page), is searchable, and its passage opens its page. `P4-SCALE` PASS: search over **1,000 documents**: median 91 to 94 ms, 90th percentile 104 to 120 ms, max 163 ms (target under one second); filling the 1,000 took 74 s on the resized embedding server (300 s before, when it kept being killed and the worker waited to retry) |
| **2. A search never returns a passage the person may not read** | `P4-ISOLATION` PASS: the other account finds nothing (0 results) and cannot open a passage by id. In CI (blocking, against PostgreSQL with the vector extension): the grant filter inside every query, cross-account, organization audience, a grant taken back |
| **3. Removing a source is proven complete** | `P4-REMOVE` PASS: 6 passages before, 0 after, search returns none of them. `OFFBOARD` PASS: both accounts offboarded, 0 passages left in the index |
| **4. The privacy record and the public policy cover uploads, parsed text and the index** | Published 2026-11-19 (`https://getlumina.pro/privacy`, "Last updated 19 November 2026"), with `privacy/facts.json` and a `review_log` line; `tests/test_privacy_policy.py` passes and is now a **blocking** CI module; `privacy/check_server.py` against the server: no failure (file uploads on and described) |

A real attachment from the owner's mailbox (a 4-page PDF) was read through the same pipeline: 28 passages.

## Found by the live proof and fixed (each with a test, merged and deployed)

| Fault | Fix |
|---|---|
| Every parse and every conversion failed ("This file could not be read"): the render service runs with `UMask=0077`, so each job's `in/` folder was 0700 and the container user could not open the file. File conversions had never worked in production either (the service had never been installed) | `render/service.py` `_write_input` sets every mode explicitly (#62) |
| Every page with no text went unread: the reader asked the model for `temperature: 0`, which `claude-sonnet-5-5` does not accept (the proxy answered 400) | No temperature in the request (#63); `ops/probe_models.py` had the same parameter |
| The embedding server was killed by its 1.5 GB cap on the first request of 32 long passages (ten restarts on 2026-11-19); a real PDF waited "to try again" | `--max-batch-tokens 4096` and 2.5 GB, the container labelled with its settings and replaced when they change (#64). Production: 8 requests of 32 long passages, 5.1 s each, no restart |
| A deploy restarted neither the render service nor the knowledge worker, so both kept the previous release's code | Both are optional units of `agentai-deploy`, restarted on a deploy and a rollback (#63; seen working on the `b0a5dd7` deploy) |
| **The assistant itself could not use any document, commitment, draft or brief tool**: the relay refused them for every real cell ("does not belong to an admitted live task"), because the bridge's origin check and the cell plugin held a fixed list of 13 older tools. The exit gates above call the services directly, so they passed regardless; found by Phase 5's assistant-panel gate | Both accept every `lumina_<name>` the relay serves; a blocking test ties them to all 42 relay tool names (#66, deployed `cddeb4c`) |

## Feature table

| # | Feature | State | Tests |
|---|---|---|---|
| 30 | File organization | **Live, on for every account** (`customer_uploads`): content scan, one catalogue, folders per project, same hash linked, the Files page, file tools through the relay | `tests/test_file_organization.py`, `Files.test.tsx` |
| 31 | OCR | **Live.** The vision model reads pages with no text (owner's decision of 2026-11-16: a vision-model parser, no bake-off); per-block confidence; low confidence said in answers; an unread page is said and retried. Proven live by `P4-SCAN` | `VisionRequest`, `Pipeline.test_a_scanned_page...` |
| 32 | Document understanding | **Live.** One structure for PDF, Word, PowerPoint, Excel, CSV, text, Markdown, HTML, images, mail; outline then section by section; **the document view opens at a cited passage and marks it** (`lumina/src/pages/DocumentView.tsx`, built in #60; the earlier note that it was missing was wrong) | `Parsing`, `DocumentView.test.tsx` |
| 33 | Table extraction | **Live.** 116 of 116 cells live; a total that does not add up is flagged, never corrected | `TablesAndCharts` |
| 34 | Chart extraction | **Live.** Every value printed or estimated; an estimate is never stated as data | `TablesAndCharts` |
| 36, 37 | Document search, semantic search | **Live.** Keyword plus meaning (self-hosted E5), grant filter inside the query and rechecked; every result cites source, page and passage | `Pipeline`, `IndexContract` (SQLite and PostgreSQL) |
| 35 | Comparison | **Live** (`P4-EVAL`) | `test_two_versions_of_a_contract_compare...` |
| 38 | Internal knowledge search | **Live.** Documents, mail and calendar in one list | `test_one_search_across_documents_mail_and_calendar...` |
| 39 | Project knowledge | **Live.** Pinned sources first inside a project | `test_inside_a_project...` |
| 40 | Organization knowledge | **Live.** Audiences by role or group, taken back at once | `test_sharing_with_the_organization...` |
| 41 | Knowledge base management | **Live.** Sources page, read again, remove, provenance | `Pipeline`, `Knowledge.test.tsx` |
| 42 | Memory correction | **Live.** Edit on the Settings Memory card, history kept | `MemoryCorrection`, `MemoryNotes.test.tsx` |
| 43 | Commitments | **Live.** Suggested from outside content, confirmed by the customer | `Commitments`, `Knowledge.test.tsx` |
| 44 to 48 | Assumptions, contradictions, source evaluation, fact verification, uncertainty | **Live** (`P4-EVAL`: conflict reported, unsupported claims flagged) | `test_sources_that_disagree...`, `test_claims_are_checked...`, `test_what_a_task_checked...` |

## Host (installed 2026-11-19)

`agentai-knowledge-db` (PostgreSQL 17 with pgvector, 127.0.0.1:5433), `agentai-embeddings` (text-embeddings-inference 1.8 on CPU, `intfloat/multilingual-e5-small`, 127.0.0.1:8890,
2.5 GB, 4,096 batch tokens), `lumina-renderer:2` in the cell engine (Debian base pinned by digest), `agentai-render.service`, `agentai-knowledge.service`; digests in
`platform/runtime.lock.json` `images`. Steps: `platform/deploy/PENDING_DEPLOY.md` (done) and `deploy/RENDERER.md`.

## Decisions taken

- **Uploads and knowledge on for every account** (owner, 2026-11-19), with the confirmations recorded on the owner's word.
- **The policy test blocks merges** now: it had been failing on `main` for days without anyone seeing it.
- **No reader bake-off** (owner, 2026-11-16: "skip the test, use the vision model"); the live scanned-page gate is the proof.

## Owner's answers used

2026-11-16: vision-model parser, self-hosted embeddings, a dedicated PostgreSQL index. 2026-11-19: publish the prepared policy as it was; uploads and knowledge on for every
account after the proof; a $10 budget for the proofs.

## Cost, unknowns, rollback

Cost: under $1 of model time for the proofs. Unknown: the vision model's accuracy on the hardest real pages (skewed photos, handwriting) is not measured beyond the live
scanned page. Rollback: turn `customer_knowledge` (and `customer_uploads`) off; the index database is separate and holds only derived data. The embedding container's old
settings: run `install.sh` with `KNOWLEDGE_EMBED_MEMORY=1500m KNOWLEDGE_EMBED_BATCH_TOKENS=8192` (not recommended).
