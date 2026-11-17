# Roadmap Phase 4 - customer knowledge

**Status (2026-11-17): DEPLOYED WITH ITS SWITCHES OFF; NOT INSTALLED ON THE HOST.** All of Phase 4 is merged (pull request #60) and on the server (`7a73420`,
migration 0050 applied). #30 file organization has been live since #50 behind `customer_uploads` (off). The rest is behind `customer_knowledge` (off), which refuses to
turn on until its three host facts and two confirmations exist. Not done, and needed before the switch: the host install (`deploy/knowledge/install.sh`, the render
service, which has never been installed here, and the knowledge worker; the permission system refused the assistant running the install as root on production),
the live proof (`deploy/phase45_live.py`, which needs the install) and the published policy (`platform/privacy/proposed/`). Deploy-day steps:
`platform/deploy/PENDING_DEPLOY.md`, "Roadmap Phase 4".

## Decisions (owner, 2026-11-16)

- Parser: a vision-model parser for pages with no text, not Docling. Pages with no text and pictures that may be charts go to the model provider, paid by Lumina.
- Embeddings: self-hosted (multilingual E5 small, text-embeddings-inference on CPU, bound to 127.0.0.1). No hosted embedding, so no new recipient of document text.
- Index: a dedicated PostgreSQL database with the vector extension (`deploy/knowledge/install.sh`), not Hindsight, not the SQLite platform file.
- Parsing runs in the render service's sealed container (no network, memory and time caps); the app never parses an untrusted file in its own process.

## Exit gate

| Gate | State |
|---|---|
| 1. The knowledge evaluation set passes (retrieval, citation, comparison, planted contradictions, unsupported claims, scanned pages) | **Passes in CI** (`tests/test_knowledge_eval.py`, a blocking gate since #60: 22 documents, 42 questions; stand-in embedder: recall@5 0.952, recall@10 0.976, top-1 0.738, citations 1.0, table cells 116 of 116, comparison, the planted conflict and all four planted unsupported claims caught). It found and #60 fixed two defects (PDF tables with empty cells read as text; numbers in words not checked). **Live run with the real reader, vision model and embedding model: waits for the install** |
| 2. A search never returns a passage the person may not read | **Proven in tests**: the grant filter runs inside every index query (`IndexContract.test_visibility_is_decided_inside_every_query`, on SQLite and on PostgreSQL), cross-account, organization audience, and a grant taken back |
| 3. Removing a source is proven complete | **Proven in tests**: passages gone at once, a down index finishes within seconds, account deletion empties the index |
| 4. The privacy record and public policy cover uploads, parsed text and the index | Record: **done** (`retention.py` rules `document_passages`, `task_checks`, `commitments`, `mail_drafts`; `data_lifecycle.py` export and erase). Public policy text and `privacy/facts.json`: **not updated** - `tests/test_privacy_policy.py` fails three checks (it already failed them on `main` for the mail and calendar copy; Phase 4 adds the index and new tables). The switch refuses to turn on until the owner confirms `policy_published` |

## Feature table

| # | Feature | State | Tests |
|---|---|---|---|
| 30 | File organization | **Live** behind `customer_uploads` (off): content scan, one catalogue, folders per project, same hash linked not stored twice, the Files page, file tools through the relay | `tests/test_file_organization.py`, `Files.test.tsx` |
| 31 | OCR | Vision-model parse of pages with no text; per-block confidence; low confidence said in answers; a page it could not read is said and retried | `Pipeline.test_a_scanned_page...`, `test_a_page_the_vision_model_could_not_read...` |
| 32 | Document understanding | One structure (headings, paragraphs, lists, tables, figures, page, position) for PDF, Word, PowerPoint, Excel, CSV, text, Markdown, HTML, images, mail; outline then section-by-section reading | `Parsing`, `test_a_long_document_is_read_by_its_outline...` |
| 33 | Table extraction | Rows, columns, headers, numbers parsed; a total that does not add up is flagged, never corrected | `TablesAndCharts` |
| 34 | Chart extraction | Every value printed or estimated; an estimate is never stated as data | `TablesAndCharts` |
| 36, 37 | Document search, semantic search | Keyword plus meaning, grant filter before ranking and rechecked after, every result cites source, page and a passage id | `Pipeline`, `IndexContract` |
| 35 | Comparison | Section then sentence alignment, added/removed/moved/changed with both places | `test_two_versions_of_a_contract_compare...` |
| 38 | Internal knowledge search | One list across documents, mail and calendar; a failing system is said, the rest still answer | `test_one_search_across_documents_mail_and_calendar...` |
| 39 | Project knowledge | Pinned sources come first inside a project | `test_inside_a_project...` |
| 40 | Organization knowledge | Audiences by role or group; taken back at once | `test_sharing_with_the_organization...` |
| 41 | Knowledge base management | Sources page (`/knowledge`, linked from Files): state, passages, read again, remove with confirmation; re-read on change; provenance | `Pipeline`, `Knowledge.test.tsx` |
| 42 | Memory correction | Edit on the Settings Memory card; a correction keeps the id, replaces the index text, keeps history | `MemoryCorrection`, `MemoryNotes.test.tsx` |
| 43 | Commitments | Commitments section on the same page; found in outside content = suggested only, the customer confirms | `Commitments`, `Knowledge.test.tsx` |
| 44 to 48 | Assumptions, contradictions, source evaluation, fact verification, uncertainty | Both sides of a conflict shown; kind and date per source; claims checked against their passage; three plain statements, no percentage | `test_sources_that_disagree...`, `test_an_old_source...`, `test_claims_are_checked...`, `test_what_a_task_checked...` |

## Not proven (to do before the switch is turned on)

- The reader bake-off on the hardest real pages (skewed receipt photo, two-column scan, stamped form, handwriting, non-English) with accuracy, time per page and memory.
- Retrieval recall at 5 and 10 and citation correctness with the real embedding model, to set the regression target; the under-one-second search over 1,000 documents on the production host.
- The install on the host (`deploy/knowledge/install.sh`, `deploy/agentai-knowledge.service`, render reader image 2) and CI's first run with the pgvector service.
- The document view that opens at a cited page and highlights the passage: the API (`/v1/knowledge/sources/<id>/document`) exists, the web view does not.
- Republish the privacy policy (names the knowledge index, parsed text, and the model provider reading pictures).

## Rollback

Turn `customer_knowledge` off: tools disappear, nothing is read or sent. The index database is separate; dropping it loses only derived data (the files stay in Files).
