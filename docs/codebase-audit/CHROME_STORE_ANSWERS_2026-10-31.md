# Lumina Chrome Web Store answers — evidence review, 31 October 2026

## Scope and confidence

Local checkout: `/Users/parsa/AgentAI`, branch `product-phases-6-11`, HEAD
`f789bf2` at the start of review. Application source was not changed.

Used the installed **codebase-memory-mcp (CBM) 0.11.0** CLI. Ran
`lumina-index status` (stale), `lumina-index refresh`, bounded architecture,
symbol search, coverage checks, and an outbound call trace from
`BrowseService._run`. Refreshed graph: **12,315 nodes, 50,441 relationships,
923 file nodes**. Read source at the boundaries rather than treating graph edges
or older planning documents as runtime proof.

This is a workspace architecture survey plus a detailed extension/data-path
review, not a claim to have read every line of every file. CBM indexes
`openclaw-project`, not the entire AgentAI folder. Coverage metadata reports
`recording_status: truncated`; directory coverage queries are unavailable.
Dependencies, secrets, archives, runtime databases, media, and excluded research
are not exhaustively indexed or inspected. The root JEV prototypes were reviewed
as separate projects through their entry documentation. Existing codebase audits
were used for navigation and cross-checked where relevant to these answers.

No production login, paid model request, store edit, certification, or submission
was performed. The uploaded Web Store ZIP was not retrieved, so these findings
describe local source, not a verified byte-for-byte match to that upload.

## Workspace and execution map

| Area | Role and evidence |
|---|---|
| `openclaw-project/lumina` | Customer React/Vite app. `src/App.tsx:24–31` mounts chat, tasks, history, files, live view, settings and generated UI under `/app`. |
| `platform/accounts` | Django identity and account-scoped HTTP boundary. `urls.py:16–82` wires authentication, requests, conversations, artifacts, browser, devices, vault, Telegram and billing. |
| `platform/agentai_platform` | Chat admission, request queue, budgets, events, execution, artifacts and integrations. `accounts/chat.py:46–58` composes ChatService with queue, ledger, events and NativeGateway. |
| `platform/agentai_platform/lifecycle` | Host/cell execution boundary. `accounts/management/commands/request_worker.py:23–45` injects BridgeRpc/NativeGateway into ChatDriver and browser RPC into the worker. |
| Request execution | `request_worker.py:53–84` claims funded work and invokes driver.execute; `chat_driver.py:141–157` admits, starts/reasserts, then supervises native execution. |
| Browser orchestration | `browse/service_main.py:31–42` selects customer Chrome, native-cell browser, or hosted runner. Presence of all three in code does not prove which is deployed. |
| Customer Chrome | `browse/extension` contains manifest, popup, background worker, executor, page helpers and packaged rules. `service_main.py:156–161` connects jobs to DeviceTransport. |
| Browser models | `browse/ladder.py:325–338` sends page-derived data and optional screenshots to a chooser; `service_main.py:22–23,125–131` configures TypeSafe/JEV and an optional experimental chooser. |
| Parallel UI | `lumina-character` is a separate UI tree; it is not what `lumina/src/App.tsx` imports. |
| Root JEV projects | `jev-browser` and `jev-window-core` are separate browser/macOS-control prototypes, not part of the extension ZIP. |
| Other workspace folders | `product`, `phase-prompts`, deployment files, audits, output, backups and cost-audit material provide contracts, operations or generated artifacts, not proof of active extension imports. |

Paths beginning `platform/` above are relative to `openclaw-project`.

The extension path is:

`Lumina UI → account APIs → browser service → DeviceTransport/WebSocket → extension Executor → Chrome Debugger API → task tab → reply/page content/screenshot → backend → model or user-facing task output`.

## Ready-to-paste Privacy answers

### Single purpose

> Connect Lumina to Chrome so it can carry out browsing tasks requested by the user in dedicated task tabs while the extension is enabled.

Evidence: `browse/extension/src/background.js:25–31,53–72,106–115`;
`lumina/src/components/YourBrowser.tsx:52–68,77–91`.

Pairing itself switches the extension on (`background.js:128–135`), so do not
promise a separate enable click is always required after pairing.

### debugger justification

> Required to carry out user-requested browsing tasks in Lumina task tabs. The extension uses chrome.debugger to inspect page content, capture screenshots, navigate, click, scroll, and enter text using the Chrome DevTools Protocol. It attaches to tabs it creates and popups opened by those tabs. Users can stop the session through the extension or Cancel on Chrome's debugging banner.

Evidence: `background.js:13–40,45–49,63–72`;
`executor.js:67–70,111–127,168–198,213–232`.

This is implemented attachment scope, not a claim that the debugger permission
itself is restricted to those tabs by Chrome.

### tabGroups justification

> Required to label and color the Lumina tab group so users can identify the tabs used for their browsing tasks.

Evidence: `background.js:16–19`. The grouping is a user-visible organization
feature; the code catches grouping failures and can continue without grouping.
Do not claim grouping is technically required to execute browser commands.

### storage justification

> Required to store the browser's pairing code, device authentication token, and enabled state locally so the extension can pair with the user's Lumina account, authenticate its connection, and report its state.

Evidence: `background.js:55–58,66,77–88,109–110,123–134,160–161`.
`chrome.storage.local` is not evidence of encryption at rest.

### Are you using remote code?

**Recommendation: keep Yes and disclose remote command execution.** This is a
policy interpretation supported by the architecture, not a finding that the
extension downloads JavaScript files. My earlier advice to select No solely
because the JS files are packaged was too categorical.

> Lumina's backend selects browsing actions for user-requested tasks and sends structured commands over a WebSocket connection. The extension interprets a fixed command set and performs browser actions through chrome.debugger and the Chrome DevTools Protocol in Lumina task tabs. All JavaScript modules and page helper functions are included in the extension package; no remote JavaScript or Wasm files are downloaded for execution. Commands supply URLs, text, coordinates, and other action parameters. This remote-control behavior is the extension's single purpose, and users can stop it from the extension or Chrome's debugging banner.

Evidence: `background.js:79–92,106–118`; `executor.js:67–70,98–107`;
`platform/agentai_platform/browse/service_main.py:156–161`;
`platform/agentai_platform/browse/devices.py:195–198`;
`browse/extension/package.py:19–20`.

Google's Manifest V3 policy covers interpreters of complex remote commands even
when commands are data, and explicitly lists the Debugger API as a permitted
remote-execution API, subject to its conditions. This is why the disclosure is
more complete than simply saying all imports are local. This review does not
guarantee Google's approval or determine the classification Google will apply.

Source: https://developer.chrome.com/docs/webstore/program-policies/mv3-requirements

## Data usage: evidence and selections

Website content is not exclusively anonymous data. Screenshots and body text can
contain personal information. The collection happens when content is sent from
Chrome to Lumina, before any backend text redaction.

| Field | Recommended answer for this implementation | Code proof / qualification |
|---|---|---|
| Website content | **Check** | `page.js:19–45` reads controls, ordinary field values, title and body text. `executor.js:120–127,187–198` returns snapshots/screenshots. `background.js:115–118` sends replies to the backend. |
| Web history | **Check** | `executor.js:73–74,111–127` returns task-tab URLs and titles. This is task browsing data, not a scan of the user's complete Chrome history. |
| Authentication information | **Check** | Pairing codes and tokens are sent in `background.js:83–88` and persisted at `109–110,132`. Saved-login fill also exists: `browse/loop.py:375–385` sends a username/password through session actions. |
| User activity | **Check** | `page.js:40–45` returns control state and scroll position. `executor.js:168–184` handles user takeover inputs. `browse/loop.py:370–385` records action metadata. No evidence here of background keylogging across unrelated tabs. |
| Personally identifiable information | **Check** | Ordinary input values and page text are returned by `page.js:19–45`. Saved-login username and cardholder-name fill are explicitly implemented at `browse/loop.py:375–405`. |
| Financial and payment information | **Check** | `browse/loop.py:388–408` sends saved cardholder name, number and expiry into fields through browser commands. `vault.py:115–131` validates/stores card data; CVV storage is refused. Stopping before payment is not equivalent to never handling payment information. |
| Personal communications | **Check if retaining the current general-purpose, signed-in-site browsing scope** | Content capture has no email/message-category exclusion (`page.js:44`; `executor.js:187–198`). The UI explicitly supports signed-in sites (`YourBrowser.tsx:79`). This is an inference about what task pages can contain, not evidence that a real user's email has been collected. |
| Health information | **Check if retaining the current general-purpose browsing scope** | The same page text and image path can capture health-related task pages. `rules.js:21–29` filters network address types, not health data; the backend's default deny list (`browse/loop.py:18`) does not categorically exclude health sites. This proves capability, not observed collection of medical records. |
| Location | **Check if retaining tasks/pages containing users' location information** | Ordinary fields, body text and screenshots can include addresses or location. No dedicated GPS collection was found in the extension runtime. Capability to capture location in a page must not be described as use of a GPS permission. |

For the current broad signed-in-site feature, disclosing all nine categories is
the conservative recommendation. The last three depend on the released feature's
actual intended scope. Code alone cannot establish which page categories users
will request or what future collection the owner plans. Do not invent observed
collection, and do not claim these categories are technically excluded.

Google defines handling broadly to include collection, transmission, use or
sharing; local processing also requires disclosure:
https://developer.chrome.com/docs/webstore/program-policies/user-data-faq

## What the privacy policy must accurately account for

- Production extension endpoint is `wss://backend.getlumina.pro/v1/device`
  (`extension/src/config.js:4`). Loopback development overrides are also allowed
  (`config.js:8–10`); do not claim it can only ever connect to production.
- Backend saves JPEGs in job folders (`browse/device_transport.py:31–54`).
- TypeSafe/JEV can receive text and screenshots (`browse/ladder.py:300–338`);
  its endpoint is configured at `browse/service_main.py:22`. The assistant
  handoff can also include an image (`browse/service.py:355–367`).
- Text redaction uses regexes (`agentai_platform/privacy.py:11–26,44–49`),
  can be disabled for browser-model text (`privacy.py:30–37` and
  `browse/loop.py:139`), and is not screenshot redaction. Do not promise universal
  anonymization or that model providers never receive personal data.
- Screenshot retention defaults to a 24-hour threshold checked every 15 minutes
  (`browse/service.py:41–42,72–80,453–477`). Active jobs are excluded; retention
  can be disabled per account; age uses directory mtime. Do not promise an
  unconditional exact 24-hour deletion deadline.
- Device records contain account association, token hash, label and timestamps
  (`browse/devices.py:125–127`); revocation removes the record (`164–170`).
- Saved login/card data uses account-derived AES-GCM encryption in the vault
  (`agentai_platform/vault.py:20,75,168`), which does not imply all database,
  screenshot, log or extension-storage data is similarly encrypted.
- Account retention command implements 30-day detailed events, 90-day chat
  projection and 180-day audit/email cleanup
  (`accounts/management/commands/retention_accounts.py:11–35`). Actual production
  scheduling and all other storage copies were not verified in this review.
- Provider configuration includes Anthropic via LiteLLM; an optional experimental
  browser writer uses OpenRouter. Configured integrations are not proof of
  current production enablement, provider contracts, training restrictions or
  provider retention. See `deploy/litellm.yaml` and
  `browse/ultrafast_brain.py`, `browse/service_main.py:119–131`.

**Verified public URL issue:** a read-only HTTP request to
`https://getlumina.pro/privacy` returned **404** on 31 October 2026. No privacy
route appears in the inspected customer SPA routes or Django URL table. Do not
enter that URL as a working policy until a policy is actually published there.
A policy may exist elsewhere; this review did not establish another valid URL.

## Certifications: not provable by source alone

The three statements about no prohibited sale/transfer, no unrelated use, and no
creditworthiness/lending use are publisher commitments. Observing task-related
data paths is not proof that every business practice, contract and provider use
complies. Third-party model processing exists, so do not interpret the first
checkbox as a declaration that data never reaches a third party.

The owner should check all three only if true for Lumina and its providers.
Code cannot supply a verified contact email, verify mailbox ownership, prove
future practices, or certify full Developer Program Policy compliance.

## Store listing and original publishing blockers

| Field/blocker | Answer/action |
|---|---|
| Language | English; current extension popup, manifest description and customer instructions are English. |
| Category | Productivity is the recommended editorial category for task automation; it is not a runtime fact. Choose the matching option offered by the dashboard. |
| Icon | Upload `browse/extension/icons/icon-128.png`. Packaging tests confirm PNG dimensions and logo layout. A manifest icon does not automatically fill the separate store image field. |
| Screenshot | Upload at least one from `browse/extension/store/screenshots/`. Tests confirm five 1280×800 JPEGs. These are real UI renders with mocked device states/demo data and caption strips (`dev/make-screenshots.mjs:1–4,36–82`), not evidence of a live customer run. |
| Contact email | Enter the publisher's chosen monitored address in publisher Settings; source code cannot choose or verify it. |
| Email verification | Follow the dashboard's verification workflow and the email link. Login email is not proof the contact email is verified. |
| Save draft | After the owner has reviewed the disclosures and completed missing information, click Save draft. No dashboard changes were made by this review. |

Detailed description to paste:

> Lumina Browser connects Chrome to your Lumina account so Lumina can carry out browsing tasks you request.
>
> Pair your browser from Lumina Settings or enter a pairing code in the extension. When enabled and selected in Lumina, the extension opens dedicated task tabs, groups them as Lumina, and performs supported actions such as navigating, clicking, scrolling, choosing options, and entering text.
>
> During tasks, page content, URLs, page titles, form information, and screenshots are sent to Lumina's backend to perform the task. Page information and screenshots may be processed by AI service providers. Task tabs can use sites you are signed in to in that Chrome profile.
>
> You can stop a session through the extension or Cancel on Chrome's debugging banner. Connected browsers can be removed in Lumina Settings. A Lumina account is required.

Do not promise automatic operation on every site, guaranteed provider privacy,
no sensitive-data handling, or features merely present in product plans.

## Verification performed

Ran from `openclaw-project/browse`:

```sh
node --test test/extension-config.test.mjs test/extension-package.test.mjs test/extension-parity.test.mjs test/extension-worker.test.mjs test/extension-bridge.test.mjs
```

**32 passed, 0 failed, 0 skipped.** These verify configuration, packaging/import
closure, image dimensions, helper/rule parity, worker behavior and the local
WebSocket bridge. They do not prove production behavior, full policy compliance,
the uploaded package contents, or business practices. The separate real-browser
executor suite was not run in this review.

No application code, permissions or production settings were modified.
