// Thin client for the account API (see platform/UI_CONTRACT.md). Same-origin, cookie session, CSRF header on writes.
let csrf: string | null = null;

export class ApiError extends Error {
  constructor(public code: string, public status: number, public category?: string, public detail?: string, public fieldErrors?: Record<string, string>) { super(code); }
}

type Listener = () => void;
const unauthorized = new Set<Listener>();
export const onUnauthorized = (fn: Listener) => { unauthorized.add(fn); return () => { unauthorized.delete(fn); }; };
export const resetCsrf = () => { csrf = null; };

async function token(signal?: AbortSignal): Promise<string> {
  if (!csrf) {
    const res = await fetch('/v1/csrf', { credentials: 'same-origin', signal });
    csrf = (await res.json()).csrf_token as string;
  }
  return csrf;
}

export async function api<T = any>(method: 'GET' | 'POST', path: string, body?: unknown, options: { timeoutMs?: number } = {}): Promise<T> {
  const controller = options.timeoutMs ? new AbortController() : undefined;
  const timer = controller ? setTimeout(() => controller.abort(), options.timeoutMs) : undefined;
  try {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (method !== 'GET') { headers['Content-Type'] = 'application/json'; headers['X-CSRFToken'] = await token(controller?.signal); }
    const res = await fetch(path, { method, credentials: 'same-origin', headers, signal: controller?.signal, body: body === undefined ? undefined : JSON.stringify(body) });
    let data: any = {};
    try { data = await res.json(); } catch (error) { if (controller?.signal.aborted) throw error; }
    if (!res.ok) {
      if (res.status === 401) unauthorized.forEach(fn => fn());
      throw new ApiError(data.error || `http_${res.status}`, res.status, data.category, data.detail, data.field_errors);
    }
    return data as T;
  } finally { if (timer !== undefined) clearTimeout(timer); }
}

export interface AppInfo {
  api_version: string;
  user: { email: string; role: string };
  assistant: { state: string };
  features: { chat: boolean; execution: boolean; files: boolean; uploads: boolean; telegram: boolean; connectors: boolean; billing_mode: string; requests: boolean; usage: boolean; browse?: boolean };
  limits: { max_message_chars: number; max_projects: number; max_conversations_per_project: number };
}
/** `outcome` is how the task ended for the customer (completed, partial, blocked, failed, cancelled), apart from `state`, which only says the run is over; `verification` says whether
 *  anything Lumina can check supports "done"; `parked` is set while the run waits for a person; `goal` marks a "keep working until complete" task and `continuing` that the next turn is on its way. */
export interface RequestRow { id: string; message: string; state: string; cancel_requested: number; result: string | null; created_epoch: number; conversation_id?: string | null; paused?: boolean; ahead?: number | null; retry_of?: string | null;
  outcome?: 'completed' | 'partial' | 'blocked' | 'failed' | 'cancelled' | null; outcome_note?: string | null; verification?: 'verified' | 'unverified' | 'not_applicable' | null; parked?: string | null; goal?: boolean; continuing?: boolean }
export interface EventRow { sequence?: number; id?: number; kind: string; payload?: { summary?: string; category?: string; status?: string; tool?: string; ref?: string }; created_at: string }
