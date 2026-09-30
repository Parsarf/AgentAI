# Screens and annotated wireframes

Open [wireframes.html](wireframes.html) in a browser. It is an interactive design
artifact: screen selection and mobile layout, synthetic clearly labeled examples.
It performs no sign-in, billing, Gateway or provider call. Reuses the existing
dashboard's overview/sidebar, now-running strip, filters, honest unknown costs
and focus styles; customer routes require the new verified account boundary.

Navigation: Overview · Projects · Work · Files · Approvals · Memory · Schedules
· Integrations · Usage & billing · Account. Internal operations is a separate
operator surface; hiding its navigation does not enforce authorization.

| Screen | Content / actions | Required states / security annotation |
|---|---|---|
| Sign-in/recovery | Maintained identity flow, recovery, safe return URL | Loading, invalid/expired recovery, rate-limited; no account enumeration; MFA for operators |
| Onboarding | Offer limits, identity verified, agent setup operation/status | Pending/failed/retry/capacity unavailable; ready only from real health+boundary proof |
| Overview | Now-running task, remaining provider allowance, alerts | Explicit observation timestamp/unknown/stale; no fictional zero spend |
| Projects | Create/name/select project; active Telegram project | Empty/quota reached/denied; all IDs resolved within authenticated account |
| Conversation | Transcript/input/send, attempts, status/budget/cancel | Sending/disconnected/history loading/budget denied/unknown submission; refresh not resubmit |
| Live work | Public plan, source/file/command/test/error/result events | Cursor reconnect/expired resync; pause timeline distinct from execution pause; private reasoning omitted |
| Files/results | Version/name/hash/type/provenance, safe preview/download/ZIP | Empty/capture failed/partial/scan pending/link expired/quota; no active HTML in dashboard origin |
| Approvals | Exact action/account/target/payload/expiry/known cost | Changed/expired/replayed/denied; unsupported native resolution shows surface/gap |
| Memory | Confirmed preferences/project context, correction/delete | Source/date/confidence, index deletion in progress, history/backups disclosure |
| Schedules | Native jobs/timezone/policy/status | Later-release unavailable; never fake running job; stricter unattended + budget needed |
| Integrations | Connector identity/scope/read-only/revoke | Disconnected/expired/refresh failed/later-release; credentials never returned |
| Usage/billing | Reserved/estimated/reconciled cost, limits, invoice/cancel | Unknown/late receipt/grace/failed checkout; redirect cannot grant paid access |
| Account/Telegram | Sessions/logout/revoke, export/delete, expiring link/project | Numeric identity verified via update, unlink immediate, single-use code; link no operator rights |
| Internal operations | Tenant deployment/version/health/incident/backup-age | Operator-only authenticated/audited scope; fixed commands; no shell/token export |

Shared patterns: semantic headings/labels, visible keyboard focus, 44px touch
targets, text alongside status color, polite live status without narrating every
event, reduced-motion support, 375px single-column view. Wireframe examples are
not accessibility or behavioral acceptance of the future product; real browser
flows run against implemented screens in Phase 15.
