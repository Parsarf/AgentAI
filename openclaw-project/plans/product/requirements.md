# Product requirement/status ledger

Canonical machine-readable ledger: [requirements.json](requirements.json).
All original cases remain in evals/cases.yaml/RESULTS.md with historical results;
new results record final-boundary applicability rather than overwriting them.
Launch/later/optional scope is decided before acceptance in product/CONTRACT.md.

| ID | Requirement | Scope | Build phase | Case | State |
|---|---|---|---|---|---|
| PROD-01 | Exact first offer and release scope | launch | 1 | P01-CONTRACT | REUSE |
| PROD-02 | Every screen annotated and responsive | launch | 1 | P01-SCREENS | REUSE |
| PROD-03 | Complete reading-list example | launch | 1 | P17-COMPLETE-WORKFLOW | PARTIAL |
| PROD-04 | Cost/capacity calculations and unknowns | launch | 1 | P01-COST | REUSE |
| FOUND-01 | Private app/control with resource caps | launch | 2 | P02-PRIVATE-SMOKE | REUSE |
| FOUND-02 | Composite tenant/project relationship constraints | launch | 2 | P02-FOREIGN-KEY | REUSE |
| FOUND-03 | Scoped repository and versioned API schemas | launch | 2 | P02-OBJECT-BOUNDARY | REUSE |
| FOUND-04 | Atomic/checksummed immutable migrations | launch | 2 | P02-MIGRATION | REUSE |
| FOUND-05 | No secrets in browser/logs and hard-disabled customer gates | launch | 2 | P02-GATES-LOGS | REUSE |
| FOUND-06 | Tenant deployment trust model/native capability inventory | launch | 2 | P02-ARCHITECTURE | PARTIAL |
| ACCOUNT-01 | Sign-in/account recovery/session revoke | launch | 3 | P15-ACCOUNT | REUSE |
| ACCOUNT-02 | Roles and audit-required mutations | launch | 3 | P15-AUDIT | REUSE |
| TENANT-01 | Isolated lifecycle create/start/stop/upgrade/delete | launch | 4 | P15-PROVISION | PARTIAL |
| TENANT-02 | Simultaneous two-customer execution isolation | launch | 4 | P15-CUSTOMER-BOUNDARY | PARTIAL |
| TENANT-03 | Measured CPU/RAM/PID/disk admission | launch | 4 | P15-CAPACITY | PARTIAL |
| USAGE-01 | Every-provider/task metering and reconciliation | launch | 5 | P15-USAGE | PARTIAL |
| USAGE-02 | Atomic concurrent reservation and hard caps | launch | 5 | P15-BUDGET | PARTIAL |
| CHAT-01 | Verified native send/stream/history/retry/cancel | launch | 6 | P15-CHAT-RECONNECT | PARTIAL |
| TG-01 | Shared ingress secure numeric account link | launch | 7 | P15-TELEGRAM | MISSING |
| TG-02 | Active project and shared dashboard history | launch | 7 | P15-CROSS-SURFACE | MISSING |
| FILES-01 | Safe uploads/types/size/quarantine/quotas | launch | 8 | P15-UPLOAD | MISSING |
| FILES-02 | Immutable artifacts/preview/download/provenance/bundle | launch | 8 | P15-ARTIFACT | MISSING |
| FILES-03 | Race-safe filesystem containment | launch | 8 | P15-FILE-BOUNDARY | MISSING |
| EVENT-01 | Durable scoped public timeline | launch | 9 | P15-LIVE-EVENTS | MISSING |
| EVENT-02 | Native task controls and approval semantics | launch | 9 | P15-APPROVAL | MISSING |
| NATIVE-01 | Restricted roles/effective policies/primary research | launch | 10 | P15-RESEARCH | PARTIAL |
| NATIVE-02 | Native coding build/browser/independent reviewer | launch | 10 | P15-NATIVE-BUILD | PARTIAL |
| NATIVE-03 | Focused debug regression | launch | 10 | P15-DEBUG | PARTIAL |
| NATIVE-04 | Selective inspectable memory/correction/deletion | launch | 10 | P15-MEMORY | PARTIAL |
| NATIVE-05 | Durable safe native task restart/resume/cancellation | launch | 10 | P15-DURABLE | PARTIAL |
| NATIVE-06 | Stricter schedules/timezone/quiet watchers | later | 10 | P15-SCHEDULE | PARTIAL |
| NATIVE-07 | Account-scoped reusable skills/proposed improvements | later | 10 | P15-SKILLS | PARTIAL |
| INT-01 | Google Gmail read-only connection | later | 11 | P15-GMAIL | PARTIAL |
| INT-02 | Google Calendar read-only connection | later | 11 | P15-CALENDAR | PARTIAL |
| INT-03 | Google Drive read-only connection | later | 11 | P15-DRIVE | PARTIAL |
| INT-04 | GitHub selected-repo read-only connection | later | 11 | P15-GITHUB | PARTIAL |
| INT-05 | Credentialed browser/session/encrypted native auth custody | later | 11 | P15-AUTH-BROWSER | PARTIAL |
| OPT-01 | Typed Jev browser adapter + transport | optional | 12 | T11-PAIRED-COMPARISON | PARTIAL |
| OPT-02 | Research middleware loader/citation/quality proof | optional | 12 | P16-RESEARCH-OPT | PARTIAL |
| BILL-01 | Checkout/invoices/entitlement transitions/cancel/failure | launch | 13 | P15-BILLING | MISSING |
| OPS-01 | Encrypted off-host tenant restore and RPO/RTO | launch | 14 | P15-RECOVERY | PARTIAL |
| OPS-02 | Monitoring/rates/alerts/incidents/rotation/release rollback | launch | 14 | P15-OPERATIONS | PARTIAL |
| OPS-03 | Disposable target guards/load/shutdown/smoke | launch | 14 | P15-LOAD-SHUTDOWN | PARTIAL |
| BETA-01 | Real customer workflow/support/payment proof | launch | 17 | P17-COMPLETE-WORKFLOW | MISSING |
| LAUNCH-01 | Final reviewed release/paid signup/capacity/rollback | launch | 18 | P18-LAUNCH | MISSING |
| PURCHASE-01 | Optional customer-funded provider purchase lifecycle | optional | 19 | P19-PURCHASE | MISSING |
| LIMIT-MONTHLY_PRICE_USD | monthly_price_usd = 79.00 | launch | 13 | P15-LIMIT-MONTHLY_PRICE_USD | MISSING |
| LIMIT-INCLUDED_PROVIDER_COST_USD | included_provider_cost_usd = 25.00 | launch | 5 | P15-LIMIT-INCLUDED_PROVIDER_COST_USD | PARTIAL |
| LIMIT-DAILY_PROVIDER_COST_USD | daily_provider_cost_usd = 5.00 | launch | 5 | P15-LIMIT-DAILY_PROVIDER_COST_USD | PARTIAL |
| LIMIT-MAX_TASK_COST_USD | max_task_cost_usd = 5.00 | launch | 5 | P15-LIMIT-MAX_TASK_COST_USD | PARTIAL |
| LIMIT-MAX_RUNNING_TASKS | max_running_tasks = 1 | launch | 5 | P15-LIMIT-MAX_RUNNING_TASKS | MISSING |
| LIMIT-MAX_QUEUED_TASKS | max_queued_tasks = 3 | launch | 5 | P15-LIMIT-MAX_QUEUED_TASKS | PARTIAL |
| LIMIT-MAX_PROJECTS | max_projects = 10 | launch | 5 | P15-LIMIT-MAX_PROJECTS | MISSING |
| LIMIT-MAX_TASK_DURATION_SECONDS | max_task_duration_seconds = 3600 | launch | 5 | P15-LIMIT-MAX_TASK_DURATION_SECONDS | MISSING |
| LIMIT-MAX_APPROVAL_WAIT_SECONDS | max_approval_wait_seconds = 86400 | launch | 5 | P15-LIMIT-MAX_APPROVAL_WAIT_SECONDS | MISSING |
| LIMIT-MAX_PROVIDER_RETRIES | max_provider_retries = 2 | launch | 5 | P15-LIMIT-MAX_PROVIDER_RETRIES | MISSING |
| LIMIT-MAX_TASK_STEPS | max_task_steps = 60 | launch | 5 | P15-LIMIT-MAX_TASK_STEPS | MISSING |
| LIMIT-MAX_MODEL_CALLS | max_model_calls = 30 | launch | 5 | P15-LIMIT-MAX_MODEL_CALLS | MISSING |
| LIMIT-MAX_SEARCH_REQUESTS | max_search_requests = 20 | launch | 5 | P15-LIMIT-MAX_SEARCH_REQUESTS | MISSING |
| LIMIT-MAX_UPLOAD_BYTES | max_upload_bytes = 10485760 | launch | 8 | P15-LIMIT-MAX_UPLOAD_BYTES | MISSING |
| LIMIT-MAX_UPLOAD_BATCH_BYTES | max_upload_batch_bytes = 26214400 | launch | 8 | P15-LIMIT-MAX_UPLOAD_BATCH_BYTES | MISSING |
| LIMIT-MAX_FILES_PER_BATCH | max_files_per_batch = 10 | launch | 8 | P15-LIMIT-MAX_FILES_PER_BATCH | MISSING |
| LIMIT-MAX_STORAGE_BYTES | max_storage_bytes = 2147483648 | launch | 8 | P15-LIMIT-MAX_STORAGE_BYTES | MISSING |
| LIMIT-MAX_ARTIFACT_BYTES | max_artifact_bytes = 104857600 | launch | 8 | P15-LIMIT-MAX_ARTIFACT_BYTES | MISSING |
| LIMIT-MAX_ZIP_UNCOMPRESSED_BYTES | max_zip_uncompressed_bytes = 262144000 | launch | 8 | P15-LIMIT-MAX_ZIP_UNCOMPRESSED_BYTES | MISSING |
| LIMIT-MAX_STREAM_CONNECTIONS | max_stream_connections = 3 | launch | 5 | P15-LIMIT-MAX_STREAM_CONNECTIONS | MISSING |
| LIMIT-MAX_MESSAGE_CHARACTERS | max_message_characters = 16000 | launch | 5 | P15-LIMIT-MAX_MESSAGE_CHARACTERS | MISSING |
| LIMIT-MAX_PROJECT_NAME_CHARACTERS | max_project_name_characters = 120 | launch | 5 | P15-LIMIT-MAX_PROJECT_NAME_CHARACTERS | MISSING |
| LIMIT-TRIAL_DAYS | trial_days = 7 | launch | 5 | P15-LIMIT-TRIAL_DAYS | PARTIAL |
| LIMIT-TRIAL_PROVIDER_COST_USD | trial_provider_cost_usd = 1.00 | launch | 5 | P15-LIMIT-TRIAL_PROVIDER_COST_USD | PARTIAL |
| LIMIT-TRIAL_PROJECTS | trial_projects = 1 | launch | 5 | P15-LIMIT-TRIAL_PROJECTS | MISSING |
| LIMIT-AUTOMATIC_OVERAGE | automatic_overage = False | launch | 13 | P15-LIMIT-AUTOMATIC_OVERAGE | MISSING |
| LIMIT-BILLING_GRACE_HOURS | billing_grace_hours = 72 | launch | 13 | P15-LIMIT-BILLING_GRACE_HOURS | MISSING |
| LIMIT-DELETION_ACTIVE_DATA_DAYS | deletion_active_data_days = 7 | launch | 14 | P15-LIMIT-DELETION_ACTIVE_DATA_DAYS | MISSING |
| LIMIT-BACKUP_EXPIRY_DAYS | backup_expiry_days = 30 | launch | 14 | P15-LIMIT-BACKUP_EXPIRY_DAYS | MISSING |
| LEGACY-T10-OWNER-TELEGRAM-REPLY | Carry forward T10-OWNER-TELEGRAM-REPLY | legacy-required | 15 | T10-OWNER-TELEGRAM-REPLY | DEFERRED_TEST |
| LEGACY-T10-OWNER-TELEGRAM-DENY | Carry forward T10-OWNER-TELEGRAM-DENY | legacy-required | 15 | T10-OWNER-TELEGRAM-DENY | DEFERRED_TEST |
| LEGACY-T10-UI-OWNER-AUTH | Carry forward T10-UI-OWNER-AUTH | legacy-required | 15 | T10-UI-OWNER-AUTH | DEFERRED_TEST |
| LEGACY-T10-APPROVAL-HOST-EXEC-CARD | Carry forward T10-APPROVAL-HOST-EXEC-CARD | legacy-required | 15 | T10-APPROVAL-HOST-EXEC-CARD | DEFERRED_TEST |
| LEGACY-T10-APPROVAL-TIMEOUT-DENY | Carry forward T10-APPROVAL-TIMEOUT-DENY | legacy-required | 15 | T10-APPROVAL-TIMEOUT-DENY | DEFERRED_TEST |
| LEGACY-T10-TRIVIAL-NO-SPAWN | Carry forward T10-TRIVIAL-NO-SPAWN | legacy-required | 15 | T10-TRIVIAL-NO-SPAWN | DEFERRED_TEST |
| LEGACY-T10-RESEARCH-CITATIONS | Carry forward T10-RESEARCH-CITATIONS | legacy-required | 15 | T10-RESEARCH-CITATIONS | DEFERRED_TEST |
| LEGACY-T10-INJECTION-NO-EFFECT | Carry forward T10-INJECTION-NO-EFFECT | legacy-required | 15 | T10-INJECTION-NO-EFFECT | DEFERRED_TEST |
| LEGACY-T10-NATIVE-BUILD-BOARD | Carry forward T10-NATIVE-BUILD-BOARD | legacy-required | 15 | T10-NATIVE-BUILD-BOARD | DEFERRED_TEST |
| LEGACY-T10-BROWSER-FLOWS | Carry forward T10-BROWSER-FLOWS | legacy-required | 15 | T10-BROWSER-FLOWS | DEFERRED_TEST |
| LEGACY-T10-INDEPENDENT-ACP-REVIEW | Carry forward T10-INDEPENDENT-ACP-REVIEW | legacy-required | 15 | T10-INDEPENDENT-ACP-REVIEW | DEFERRED_TEST |
| LEGACY-T10-MEMORY-SELECTIVE-RECALL | Carry forward T10-MEMORY-SELECTIVE-RECALL | legacy-required | 15 | T10-MEMORY-SELECTIVE-RECALL | DEFERRED_TEST |
| LEGACY-T10-MEMORY-CORRECTION-DELETION | Carry forward T10-MEMORY-CORRECTION-DELETION | legacy-required | 15 | T10-MEMORY-CORRECTION-DELETION | DEFERRED_TEST |
| LEGACY-T10-DURABLE-RESUME-CANCELLATION | Carry forward T10-DURABLE-RESUME-CANCELLATION | legacy-required | 15 | T10-DURABLE-RESUME-CANCELLATION | DEFERRED_TEST |
| LEGACY-T10-SCHEDULING-ADMISSION | Carry forward T10-SCHEDULING-ADMISSION | legacy-required | 15 | T10-SCHEDULING-ADMISSION | DEFERRED_TEST |
| LEGACY-T10-INTEGRATION-AUTH-FAIL-CLOSED | Carry forward T10-INTEGRATION-AUTH-FAIL-CLOSED | legacy-required | 15 | T10-INTEGRATION-AUTH-FAIL-CLOSED | DEFERRED_TEST |
| LEGACY-T10-BUDGET-DAILY-CAP | Carry forward T10-BUDGET-DAILY-CAP | legacy-required | 15 | T10-BUDGET-DAILY-CAP | DEFERRED_TEST |
| LEGACY-T10-BUDGET-MONTHLY-CAP | Carry forward T10-BUDGET-MONTHLY-CAP | legacy-required | 15 | T10-BUDGET-MONTHLY-CAP | DEFERRED_TEST |
| LEGACY-T10-BUDGET-DB-OUTAGE-FAIL-CLOSED | Carry forward T10-BUDGET-DB-OUTAGE-FAIL-CLOSED | legacy-required | 15 | T10-BUDGET-DB-OUTAGE-FAIL-CLOSED | DEFERRED_TEST |
| LEGACY-T10-OPS-SCHEDULED-BACKUP-FIRES | Carry forward T10-OPS-SCHEDULED-BACKUP-FIRES | legacy-required | 15 | T10-OPS-SCHEDULED-BACKUP-FIRES | DEFERRED_TEST |
| LEGACY-T10-OPS-RESTORE-DRILL | Carry forward T10-OPS-RESTORE-DRILL | legacy-required | 15 | T10-OPS-RESTORE-DRILL | DEFERRED_TEST |
| LEGACY-T10-OPS-ROLLBACK | Carry forward T10-OPS-ROLLBACK | legacy-required | 15 | T10-OPS-ROLLBACK | DEFERRED_TEST |
| LEGACY-T10-DASH-AUTH | Carry forward T10-DASH-AUTH | legacy-required | 15 | T10-DASH-AUTH | DEFERRED_TEST |
| LEGACY-T10-DASH-CSRF-ORIGINS | Carry forward T10-DASH-CSRF-ORIGINS | legacy-required | 15 | T10-DASH-CSRF-ORIGINS | DEFERRED_TEST |
| LEGACY-T10-DASH-FILE-TRAVERSAL | Carry forward T10-DASH-FILE-TRAVERSAL | legacy-required | 15 | T10-DASH-FILE-TRAVERSAL | DEFERRED_TEST |
| LEGACY-T10-DASH-DOWNLOAD-REPLAY | Carry forward T10-DASH-DOWNLOAD-REPLAY | legacy-required | 15 | T10-DASH-DOWNLOAD-REPLAY | DEFERRED_TEST |
| LEGACY-T10-DASH-REVOCATION | Carry forward T10-DASH-REVOCATION | legacy-required | 15 | T10-DASH-REVOCATION | DEFERRED_TEST |
| LEGACY-T10-DASH-AUDIT-FAIL | Carry forward T10-DASH-AUDIT-FAIL | legacy-required | 15 | T10-DASH-AUDIT-FAIL | DEFERRED_TEST |
| LEGACY-T10-DASH-REDACTION | Carry forward T10-DASH-REDACTION | legacy-required | 15 | T10-DASH-REDACTION | DEFERRED_TEST |
| LEGACY-T10-DASH-DISABLED-CONTROLS | Carry forward T10-DASH-DISABLED-CONTROLS | legacy-required | 15 | T10-DASH-DISABLED-CONTROLS | DEFERRED_TEST |
| LEGACY-T10-SECURITY-BUDGET-PROOF | Carry forward T10-SECURITY-BUDGET-PROOF | legacy-required | 15 | T10-SECURITY-BUDGET-PROOF | DEFERRED_TEST |
| LEGACY-T11-ADAPTER-ROBUSTNESS | Carry forward T11-ADAPTER-ROBUSTNESS | optional | 16 | T11-ADAPTER-ROBUSTNESS | DEFERRED_TEST |
| LEGACY-T11-BUDGET-OUTAGE-FALLBACK | Carry forward T11-BUDGET-OUTAGE-FALLBACK | optional | 16 | T11-BUDGET-OUTAGE-FALLBACK | DEFERRED_TEST |
| LEGACY-T11-CONFIDENCE-CALIBRATION | Carry forward T11-CONFIDENCE-CALIBRATION | optional | 16 | T11-CONFIDENCE-CALIBRATION | DEFERRED_TEST |
| LEGACY-T11-PAIRED-COMPARISON | Carry forward T11-PAIRED-COMPARISON | optional | 16 | T11-PAIRED-COMPARISON | DEFERRED_TEST |
| LEGACY-T10-DASH2-LIVE-SSE | Carry forward T10-DASH2-LIVE-SSE | legacy-required | 15 | T10-DASH2-LIVE-SSE | DEFERRED_TEST |
| LEGACY-T10-DASH2-REDACTION-LIVE | Carry forward T10-DASH2-REDACTION-LIVE | legacy-required | 15 | T10-DASH2-REDACTION-LIVE | DEFERRED_TEST |
| LEGACY-T10-DASH2-FILE-CONTAINMENT-RACE | Carry forward T10-DASH2-FILE-CONTAINMENT-RACE | legacy-required | 15 | T10-DASH2-FILE-CONTAINMENT-RACE | DEFERRED_TEST |
| LEGACY-T10-DASH2-JEV-TOGGLE | Carry forward T10-DASH2-JEV-TOGGLE | legacy-required | 15 | T10-DASH2-JEV-TOGGLE | DEFERRED_TEST |
| RETENTION-CHAT | chat/task summaries: 90days rolling, active deletion≤7days | launch | 3 | P15-RETENTION-CHAT | PARTIAL |
| RETENTION-MEMORY | confirmed memory: until corrected/deleted, retrieval index removal | launch | 10 | P15-RETENTION-MEMORY | MISSING |
| RETENTION-ARTIFACT | uploads and artifact versions: until deleted or30days subscription end | launch | 8 | P15-RETENTION-ARTIFACT | MISSING |
| RETENTION-EVENTS | detailed timeline: 30days/cursor resync | launch | 9 | P15-RETENTION-EVENTS | MISSING |
| RETENTION-AUDIT | minimal audit metadata: 180days restricted retention | launch | 3 | P15-RETENTION-AUDIT | REUSE |
| RETENTION-BILLING | financial records: 7years proposed pending jurisdiction review | launch | 13 | P15-RETENTION-BILLING | MISSING |
| RETENTION-PROVIDER | provider copies: terms/region reviewed before route activation | launch | 5 | P15-RETENTION-PROVIDER | MISSING |

Phase3 targeted identity/audit/retention boundary checks PASS; full Phase15 acceptance remains NOT_RUN. RETENTION-CHAT is PARTIAL until native/file/index/restore adapters exist. See [Phase3 record](phase-03.md).

Phase4 target clarified to one service-operated VPS/shared domain. Assessment/calculator PASS; lifecycle/isolation implementation remains incomplete and current agent admission0. [Assessment](phase-04-single-vps-assessment.md).

Phase 4 assessment evidence: [manifest](../../evidence/product/phase-04/20260930T011410Z/manifest.json). Lifecycle and customer activation remain incomplete.

Current capacity target: [existing-VPS trial](../../../product/EXISTING_VPS_TRIAL.md). Two invited accounts share one global task slot; parallel runtime proof is retained as a capacity-expansion gate. All 121 requirements remain.

## Phase4 continuation — 2026-10-01

TENANT-01/02/03 remain PARTIAL; independent host journal/binding custody and
Unix controller transport now exist. Native backend, worker isolation, quotas,
credentials, dispatch admission and usable host profile remain activation gaps.
No native acceptance pass or phase-order change. All121 requirements retained.
See [current Phase4 record](phase-04.md) and latest manifest.
