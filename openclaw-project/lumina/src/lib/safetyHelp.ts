// What each safety switch does, in plain words, for the "What does this do?" lines of the Safety console. Written from what the code actually does (platform/OPERATIONS.md,
// "Safety menu"); a switch the code does not read yet says so. UI-free, so any design can show the same words. A backend test fails if a switch exists with no entry here.
import type { SafetyFeature } from './safety';

export interface Help {
  /** what it does */
  does: string;
  /** why it exists */
  why: string;
  /** what changes while it is on */
  on: string;
  /** what is allowed, or no longer protected, while it is off */
  off: string;
}

const FIXED = "It can't be switched here.";
const NOTHING = 'Nothing changes yet: no code reads this switch.';

export const HELP: Record<string, Help> = {
  // -- Lumina platform
  budget_caps: {
    does: 'Checks each task against your spending limits (per task, per day, per month) and holds the money before the task starts.',
    why: 'So a task can never spend more than your plan allows.',
    on: 'A task that would go over a limit is refused before it starts.',
    off: "Tasks start with no limit check and no money held. The model provider's own caps still apply.",
  },
  queue_limit: {
    does: 'Allows at most 3 tasks waiting at the same time for your account.',
    why: 'Keeps one account from piling up work.',
    on: 'A fourth waiting task is refused until one has started.',
    off: 'Any number of tasks can wait. (Both the queue limit and the plan limit follow this switch.)',
  },
  rate_limits: {
    does: "Limits how often your account can call the app's routes: starting tasks, browser controls, saved logins and so on.",
    why: 'Slows down a runaway script or a stuck screen.',
    on: "Calls over the limit are answered with 'rate limited'.",
    off: "Your account's calls are not rate limited. Sign-in, sign-up and recovery limits stay on, and so does this menu's own limit.",
  },
  routing_policy: {
    does: 'Rules that can refuse or reshape how a request runs.',
    why: 'To keep a request from running a way it should not.',
    on: NOTHING + ' The router is not in the live request path yet.',
    off: NOTHING,
  },
  confirmations: {
    does: 'Terms and cost acknowledgements before a feature is used.',
    why: 'So you agree to what a feature costs or does before it runs.',
    on: NOTHING + ' The current app shows none.',
    off: NOTHING,
  },
  // -- Browser
  payment_stop: {
    does: 'Hands the browser back to you when it reaches a checkout or payment page.',
    why: 'So nothing is bought unless you do it yourself.',
    on: 'The browser stops before any model is asked and waits for you. With a saved card it can fill the card in, but you enter the security code and place the order.',
    off: "The browser carries on through payment pages and the assistant decides what to do next. Order buttons are still held if 'Approval for sensitive clicks' is on.",
  },
  sensitive_approval: {
    does: 'Stops the browser before it clicks something consequential (pay, buy, order, delete, send, confirm, sign out) or types into a password field.',
    why: 'Those actions are hard to undo.',
    on: 'The page is handed to you, with the control it wanted to press.',
    off: 'Those clicks go ahead without asking you.',
  },
  denied_sites: {
    does: "Refuses banking and trading sites (PayPal, Chase, Coinbase and similar), and stops at 'verify you are human' checks and at sign-in pages.",
    why: 'The browser cannot pass human checks, never types passwords, and should not roam your bank.',
    on: 'It refuses the site, or stops and hands the page to you.',
    off: 'It visits those sites and the assistant is shown sign-in and check pages.',
  },
  // -- Data and privacy
  personal_data_scrub: {
    does: 'Removes emails, phone numbers, card and account numbers, addresses and keys from the page text and labels sent to the browser model (JEV).',
    why: 'That model only needs the shape of the page, not your personal data.',
    on: 'Personal details are replaced by [redacted] before the text leaves.',
    off: 'Page text and labels go to JEV as they are. Stored traces and logs are still scrubbed.',
  },
  vault_notice: {
    does: 'Requires you to accept the notice before a login or card is saved.',
    why: 'So you know what saving means.',
    on: 'A save without the accepted notice is refused.',
    off: 'A save no longer needs the tick. A card security code is never stored, either way.',
  },
  secret_redaction: {
    does: 'Hides keys, tokens and passwords in the event records the app stores.',
    why: 'So secrets do not end up in stored history.',
    on: 'Matches are replaced by [redacted] before an event is stored.',
    off: 'New event records keep what the text says. The tool summaries in the Activity window are still redacted.',
  },
  ssrf_guard: {
    does: "Stops the assistant's browser reaching private addresses, internal names and cloud metadata endpoints.",
    why: "A web page must not be able to aim the browser at your host's internal network.",
    on: 'Such addresses are refused.',
    off: "The browser may open them (the network firewall around every assistant still applies). The cell's own browser follows at its next start.",
  },
  screenshot_retention: {
    does: "Deletes the browser's screenshots a day after the task.",
    why: 'Pages can show personal data.',
    on: 'Pictures are removed after 24 hours.',
    off: 'Your pictures are kept until you turn this back on; the next sweep then removes the old ones.',
  },
  // -- Prompt-injection defenses
  untrusted_page_text: {
    does: "Removes sentences on a web page that are aimed at the AI (like 'ignore your instructions') before a model reads the page.",
    why: 'A web page must not be able to give orders to the assistant.',
    on: 'Such sentences are replaced by a short marker and the task carries on.',
    off: 'Page text is passed on as it is, only shortened.',
  },
  assistant_output_cleaning: {
    does: 'Shortens and cleans the task, steps, search terms and choices the assistant sends to the browser.',
    why: 'If a page steered the assistant, its words should not carry the attack further.',
    on: 'Attack-style sentences are replaced and long text is cut.',
    off: 'Only the length limit remains. Plans in chat are always cleaned.',
  },
  // -- Input limits and validation
  message_length_limit: {
    does: 'Refuses messages over 16,000 characters.',
    why: 'Keeps one message from swamping a request.',
    on: 'Always applies.',
    off: "The database enforces it too, so it can't be switched here.",
  },
  project_chat_limits: {
    does: 'Allows at most 10 projects per account and 100 conversations per project.',
    why: 'Keeps an account tidy and bounded.',
    on: 'Creating more is refused.',
    off: 'No such limit.',
  },
  upload_limits: {
    does: 'Limits uploads to 10 MiB a file, and 25 MiB and 10 files a batch.',
    why: 'Keeps one upload from filling storage or stalling the app.',
    on: 'Larger or more numerous files are refused.',
    off: "Size and count are not checked. The file-type and content checks always run, and the storage quota stays.",
  },
  block_validation: {
    does: 'Checks that the cards, tables and plans the assistant makes match a fixed shape.',
    why: 'The code builds on the checked result, so it cannot be skipped.',
    on: 'Always applies.',
    off: FIXED,
  },
  // -- Sign-in and sessions
  login_limits: {
    does: 'Limits password tries per address and per network.',
    why: 'Slows down password guessing.',
    on: 'Always applies. It is set for the whole server.',
    off: FIXED,
  },
  csrf_protection: {
    does: "Requires every write to carry the page's secret token.",
    why: "So another website cannot act as you in the app.",
    on: 'Always applies. It is set for the whole server.',
    off: FIXED,
  },
  session_epochs: {
    does: 'Ends your sessions when a password changes or an account is revoked.',
    why: 'So a stolen session stops working when you take back control.',
    on: 'Always applies.',
    off: FIXED,
  },
  operator_mfa: {
    does: 'Operators need a second sign-in step and a time-limited grant for each action.',
    why: 'Keeps staff access narrow and recorded.',
    on: 'Always applies. It is set for the whole server.',
    off: FIXED,
  },
  // -- OpenClaw assistants
  tool_ceilings: {
    does: "Stops the assistant using the cell's browser tool directly: it has to go through Lumina's browser rules.",
    why: "So the browser's payment, sign-in and privacy rules cannot be walked around.",
    on: 'The assistant may not call the browser tool itself.',
    off: "The assistant may use the browser tool itself, outside Lumina's browser rules. It takes effect the next time your assistant starts.",
  },
  web_limits: {
    does: 'Controls which agents may fetch, search or browse.',
    why: 'To keep an agent off the web when it has no need.',
    on: NOTHING + ' Each assistant has one agent today.',
    off: NOTHING,
  },
  cell_limits: {
    does: 'Memory, CPU, filesystem and network limits on your assistant cell (2 GiB and one CPU).',
    why: 'They protect the whole host, so no assistant can starve the others.',
    on: 'Always applies.',
    off: 'Set on the server, not here.',
  },
  // -- Server hardening
  unit_sandboxing: {
    does: 'The limits the server places on each Lumina service.',
    why: 'If one service is compromised, it cannot reach the rest of the host.',
    on: 'Always applies. It is set in deploy files on the server.',
    off: FIXED,
  },
  cell_container_isolation: {
    does: 'Runs each assistant in its own container with no access to the host.',
    why: 'Keeps one account\'s assistant away from everything else.',
    on: 'Always applies. It is set on the server.',
    off: FIXED,
  },
  proxy_rules: {
    does: 'Decides which paths are public and which security headers are set (Caddy).',
    why: 'Keeps private routes off the open internet.',
    on: 'Always applies. It is set on the server.',
    off: FIXED,
  },
  provider_backstops: {
    does: 'Daily and monthly caps on the model provider keys.',
    why: "A last stop if Lumina's own spending checks ever failed.",
    on: 'Always applies. It is set at the provider.',
    off: FIXED,
  },
  bridge_restrictions: {
    does: 'The fixed list of calls the cell bridge allows, root-only browser access and named page scripts.',
    why: "So the app and the browser service can only ask an assistant's cell for what they are meant to.",
    on: 'Always applies. It is set in code.',
    off: FIXED,
  },
  cell_key_limits: {
    does: "Limits requests and tokens per minute on each assistant's model key (30 requests and 200,000 tokens).",
    why: 'Bounds a runaway assistant on its own.',
    on: 'Always applies. It is set when the key is issued.',
    off: FIXED,
  },
  cell_firewall: {
    does: 'Keeps every assistant off private networks and away from other assistants.',
    why: 'A compromised assistant cannot reach the host or its neighbours.',
    on: 'Always applies. It is set on the server.',
    off: FIXED,
  },
  // -- Core protections
  tenant_isolation: {
    does: "Keeps each account's data separate from every other account.",
    why: 'The basic promise that your data is yours.',
    on: 'Always applies.',
    off: FIXED,
  },
  vault_encryption: {
    does: 'Encrypts saved logins, cards and provider keys.',
    why: 'So a copy of the database does not reveal them.',
    on: 'Always applies.',
    off: FIXED,
  },
  audit_log: {
    does: 'Keeps a record of sensitive actions.',
    why: 'So you can see who did what, and when.',
    on: 'Always applies.',
    off: FIXED,
  },
};

/** The explanation for a switch. A switch this file does not know yet falls back to its one-line description, and says what is not known. */
export const helpFor = (f: SafetyFeature): Help => HELP[f.key] ?? {
  does: f.plain, why: 'See the description.', on: f.wired ? 'The protection applies.' : NOTHING, off: f.wired ? 'The protection no longer applies.' : NOTHING,
};
