// Action dispatch: the only way generated UI causes anything to happen. Every action is parsed against the allowlist, authorised against live state,
// rate limited, confirmed when consequential, de-duplicated by an idempotency key, executed through an injected environment, and audited.
// Nothing here trusts a permission, id or target the model supplied: ids are checked against what the server/live state says, and the server re-validates.
import { actionSchema, type Action } from './schemas';
import { safeFilePath, safeInternalPath } from './safety';

export type PhaseState = 'pending' | 'running' | 'awaiting_approval' | 'completed' | 'failed' | 'skipped' | 'cancelled';
export interface ActionEnv {
  /** Local, deterministic UI state: no network, no model. */
  local(action: Extract<Action, { kind: `local.${string}` }>): boolean;
  /** Sends the person's own message (what they confirmed is exactly what is sent). */
  send(message: string, key: string): Promise<void>;
  /** Approve/skip/retry one phase through the existing block endpoints. */
  phase(planBlockId: string, phaseId: string, verb: 'approve' | 'skip' | 'retry', key: string): Promise<void>;
  retryRequest(requestId: string, key: string): Promise<void>;
  navigate(path: string): void;
  download(path: string): Promise<void>;
  /** Live phase state from the server's block list, or null when this plan/phase is not in this chat. */
  phaseState(planBlockId: string, phaseId: string): PhaseState | null;
  /** Shows exactly what will happen and resolves with the person's answer. */
  confirm(summary: { title: string; detail: string; destructive: boolean }): Promise<boolean>;
  audit(entry: AuditEntry): void;
  now(): number;
}
export interface AuditEntry { at: number; kind: string; outcome: 'done' | 'refused' | 'declined' | 'failed' | 'duplicate' | 'rate_limited'; detail: string; key: string }
export type Result = { ok: true } | { ok: false; reason: 'invalid' | 'forbidden' | 'declined' | 'rate_limited' | 'duplicate' | 'failed'; message: string; fieldErrors?: Record<string, string> };

const CONSEQUENTIAL = new Set(['agent.approve', 'agent.deny', 'agent.retry', 'agent.request', 'file.download']);
const NEEDS_CONFIRM = new Set(['agent.approve', 'agent.deny', 'agent.retry']);

/** A small per-dispatcher budget so a runaway document cannot fire actions in a loop. The server enforces its own limits as well. */
export class Dispatcher {
  private done = new Map<string, number>(); private recent: number[] = [];
  constructor(private env: ActionEnv, private opts: { maxPerMinute?: number; scope?: string } = {}) {}

  /** Idempotency key: the same action in the same scope maps to the same key, so a double click or replay is one effect. */
  key(a: Action, nonce = ''): string {
    const s = JSON.stringify(a, Object.keys(a).sort()); let h = 5381; for (const c of `${this.opts.scope ?? ''}|${s}|${nonce}`) h = ((h << 5) + h + c.charCodeAt(0)) >>> 0;
    return `gen${h.toString(16).padStart(8, '0')}${(this.opts.scope ?? '').replace(/[^a-z0-9]/gi, '').slice(0, 16)}`;
  }

  async dispatch(raw: unknown, options: { nonce?: string; destructiveStyle?: boolean } = {}): Promise<Result> {
    const parsed = actionSchema.safeParse(raw);
    const key = parsed.success ? this.key(parsed.data, options.nonce) : 'invalid';
    const log = (outcome: AuditEntry['outcome'], detail: string, kind = parsed.success ? parsed.data.kind : 'unknown') => this.env.audit({ at: this.env.now(), kind, outcome, detail: detail.slice(0, 200), key });
    if (!parsed.success) { log('refused', parsed.error.issues[0]?.message ?? 'invalid'); return { ok: false, reason: 'invalid', message: 'That action is not allowed.' }; }
    const a = parsed.data;

    if (a.kind.startsWith('local.')) { const ok = this.env.local(a as any); log(ok ? 'done' : 'refused', a.kind); return ok ? { ok: true } : { ok: false, reason: 'invalid', message: 'Nothing on this page matches that.' }; }

    // authorisation against live state, never against what the document says
    if (a.kind === 'navigate.internal') { const p = safeInternalPath(a.path); if (!p) { log('refused', 'path'); return { ok: false, reason: 'forbidden', message: 'That page is not available.' }; } this.env.navigate(p); log('done', p); return { ok: true }; }
    if (a.kind === 'file.download' && !safeFilePath(a.path)) { log('refused', 'path'); return { ok: false, reason: 'forbidden', message: 'That file is not available.' }; }
    if (a.kind === 'agent.approve' || a.kind === 'agent.deny' || (a.kind === 'agent.retry' && a.planBlockId && a.phaseId)) {
      const st = this.env.phaseState((a as any).planBlockId, (a as any).phaseId);
      const want: PhaseState[] = a.kind === 'agent.retry' ? ['failed'] : ['awaiting_approval'];
      if (st === null || !want.includes(st)) { log('refused', `phase is ${st ?? 'unknown'}`); return { ok: false, reason: 'forbidden', message: st === null ? 'That step is not part of this chat.' : `That step is ${st.replace('_', ' ')}, so this is no longer possible.` }; }
    }
    if (a.kind === 'agent.retry' && !(a.planBlockId && a.phaseId) && !a.requestId) { log('refused', 'retry target'); return { ok: false, reason: 'invalid', message: 'Nothing to retry.' }; }

    if (this.done.has(key)) { log('duplicate', 'already handled'); return { ok: false, reason: 'duplicate', message: 'Already done.' }; }
    const now = this.env.now(); this.recent = this.recent.filter(t => now - t < 60_000);
    if (CONSEQUENTIAL.has(a.kind) && this.recent.length >= (this.opts.maxPerMinute ?? 8)) { log('rate_limited', 'too many'); return { ok: false, reason: 'rate_limited', message: 'Too many actions in a minute. Wait a moment.' }; }

    if (NEEDS_CONFIRM.has(a.kind) || options.destructiveStyle) {
      const verb = a.kind === 'agent.approve' ? 'Approve this step' : a.kind === 'agent.deny' ? 'Skip this step' : a.kind === 'agent.retry' ? 'Retry' : 'Continue';
      const yes = await this.env.confirm({ title: verb + '?', detail: a.kind === 'agent.approve' ? 'Lumina will go ahead with it.' : a.kind === 'agent.deny' ? 'Lumina will not do it.' : 'Lumina will try again.', destructive: a.kind === 'agent.deny' || !!options.destructiveStyle });
      if (!yes) { log('declined', 'person said no'); return { ok: false, reason: 'declined', message: 'Cancelled.' }; }
    }
    this.done.set(key, now); this.recent.push(now);                  // claimed before the call so a second click during the call is a duplicate
    try {
      if (a.kind === 'agent.request') await this.env.send(a.message, key);
      else if (a.kind === 'agent.approve') await this.env.phase(a.planBlockId, a.phaseId, 'approve', key);
      else if (a.kind === 'agent.deny') await this.env.phase(a.planBlockId, a.phaseId, 'skip', key);
      else if (a.kind === 'agent.retry') { if (a.planBlockId && a.phaseId) await this.env.phase(a.planBlockId, a.phaseId, 'retry', key); else await this.env.retryRequest(a.requestId!, key); }
      else if (a.kind === 'file.download') await this.env.download(a.path);
      log('done', a.kind);
      return { ok: true };
    } catch (error) {
      this.done.delete(key);                                           // a failed attempt may be tried again
      log('failed', error instanceof Error ? error.message : 'failed');
      return { ok: false, reason: 'failed', message: 'That did not go through. Nothing was changed; you can try again.' };
    }
  }
}

/** Message a form sends: the person's lead-in plus one line per answered field. Built here, not by the model, so what is confirmed is what is sent. */
export function formMessage(lead: string, rows: Array<{ label: string; value: string }>): string {
  return [lead.trim(), ...rows.filter(r => r.value !== '').map(r => `- ${r.label}: ${r.value}`)].join('\n').slice(0, 1500);
}
