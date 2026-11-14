import { beforeEach, describe, expect, it } from 'vitest';
import { FAILS_BEFORE_POLL, HELLO_MS, WorkClient, backoff, pollEvery, type Source } from './workClient';
import type { Detail, Listing, TaskSummary, TaskView } from './work';

const task = (over: Partial<TaskSummary> = {}) => ({ id: 'r1', phase: 'working', conversation_id: 'c', title: 't', needs: [], now: [], steps: 0, ...over }) as TaskSummary;
const listing = (rev: string, tasks: TaskSummary[] = [task()]): Listing => ({ rev, tasks, attention: 0 });
const detail = (rev: string, cursor: number, rows: any[] = [], over: Partial<TaskView> = {}): Detail => ({ task: { ...task(), rev, messages: 1, ...over } as TaskView, rows, cursor });

/** A world the client lives in: a clock, timers that run when time is advanced, a server that answers GET/POST, and streams the test can speak through. */
function world(opts: { ticket?: 'ok' | 404 | 500; stream?: boolean } = {}) {
  let now = 0; let hidden = false; const timers: { at: number; fn: () => void; id: number }[] = []; let seq = 0;
  const gets: string[] = []; const posts: string[] = []; const streams: (Source & { url: string; closed: boolean; say(type: string, data: unknown): void; fail(): void })[] = [];
  const server = { list: listing('L1'), detail: detail('D1', 0) as Detail | null, ticket: opts.ticket ?? 'ok' };
  let visibility: (() => void) | null = null;
  const client = new WorkClient({
    get: async <T,>(path: string) => {
      gets.push(path);
      if (path.startsWith('/v1/work/')) { if (!server.detail) throw { status: 404 }; const q = new URLSearchParams(path.split('?')[1]); return (q.get('rev') === server.detail.task.rev ? { unchanged: true, rev: server.detail.task.rev, cursor: server.detail.cursor } : server.detail) as T; }
      return (path.includes(`rev=${server.list.rev}`) ? { unchanged: true, rev: server.list.rev } : server.list) as T;
    },
    post: async <T,>(path: string) => { posts.push(path); if (server.ticket !== 'ok') throw { status: server.ticket }; return { ticket: 'T' + posts.length, path: '/v1/push', expires_in: 90 } as T; },
    open: opts.stream === false ? undefined : (url => {
      const on: Record<string, ((e: { data: string }) => void)[]> = {};
      const s = { url, closed: false, onerror: null as any, addEventListener: (t: string, f: any) => { (on[t] ??= []).push(f); }, close() { s.closed = true; },
        say(type: string, data: unknown) { on[type]?.forEach(f => f({ data: JSON.stringify(data) })); }, fail() { s.onerror?.({}); } };
      streams.push(s); return s;
    }),
    hidden: () => hidden, onVisibility: fn => { visibility = fn; return () => { visibility = null; }; },
    now: () => now, setTimeout: (fn, ms) => { const id = ++seq; timers.push({ at: now + ms, fn, id }); return id; }, clearTimeout: h => { const i = timers.findIndex(t => t.id === h); if (i >= 0) timers.splice(i, 1); },
  });
  const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
  const advance = async (ms: number) => {
    const until = now + ms;
    for (;;) { timers.sort((a, b) => a.at - b.at); const next = timers[0]; if (!next || next.at > until) break; timers.shift(); now = next.at; next.fn(); await settle(); }
    now = until; await settle();
  };
  return { client, server, gets, posts, streams, settle, advance, hide(v: boolean) { hidden = v; visibility?.(); }, last: () => streams[streams.length - 1] };
}
const query = (url: string) => Object.fromEntries(new URLSearchParams(url.split('?')[1]));

describe('pacing', () => {
  it('asks faster while something is moving, slower while something is open, and rarely otherwise', () => {
    expect(pollEvery([task()])).toBe(1500); expect(pollEvery([task({ phase: 'needs_you' })])).toBe(4000); expect(pollEvery([task({ phase: 'ended' })])).toBe(15000);
    expect([1, 2, 3, 9].map(backoff)).toEqual([500, 1000, 2000, 15000]);
  });
});

describe('the stream', () => {
  let w: ReturnType<typeof world>;
  beforeEach(() => { w = world(); });

  it('shows the list at once, then streams with a ticket and takes state as it is pushed', async () => {
    w.client.start(); await w.settle();
    expect(w.client.state.loaded).toBe(true);                                        // the first paint did not wait for the stream
    expect(w.posts).toEqual(['/v1/work/ticket']);
    expect(query(w.last().url)).toMatchObject({ t: 'T1', focus: '', after: '0' });
    w.last().say('hello', { window: 45 });
    expect(w.client.state.mode).toBe('stream');
    w.last().say('list', listing('L2', [task({ phase: 'needs_you' })]));
    expect(w.client.state.tasks[0].phase).toBe('needs_you'); expect(w.client.state.rev).toBe('L2');
    const asked = w.gets.length; await w.advance(20_000);
    expect(w.gets.length).toBe(asked);                                               // while streaming, nothing is polled
  });

  it('focuses the stream on the task a screen is watching and merges rows by cursor', async () => {
    w.client.start(); await w.settle(); w.last().say('hello', {});
    const stop = w.client.watch('r1'); await w.advance(50);
    expect(query(w.last().url).focus).toBe('r1');
    w.last().say('hello', {});
    w.last().say('task', detail('D2', 2, [{ key: 'a', first: 1, seq: 1, status: 'running' }, { key: 'b', first: 2, seq: 2, status: 'running' }]));
    w.last().say('task', detail('D3', 3, [{ key: 'a', first: 1, seq: 3, status: 'done' }]));
    expect(w.client.state.details.r1.rows.map((r: any) => [r.key, r.status])).toEqual([['a', 'done'], ['b', 'running']]);
    expect(w.client.state.details.r1.cursor).toBe(3);
    stop(); await w.advance(50);
    expect(query(w.last().url).focus).toBe('');
  });

  it('reconnects with the cursors it holds when the window ends, reusing a ticket that is still good', async () => {
    w.client.start(); w.client.watch('r1'); await w.advance(50); w.last().say('hello', {});
    w.last().say('list', listing('L7')); w.last().say('task', detail('D7', 12));
    const before = w.streams.length;
    w.last().say('reopen', {}); await w.settle();
    expect(w.streams.length).toBe(before + 1); expect(w.streams[before - 1].closed).toBe(true);
    expect(query(w.last().url)).toMatchObject({ rev: 'L7', frev: 'D7', after: '12', focus: 'r1' });
    expect(w.posts.length).toBe(1);
  });

  it('retries a dropped connection with a growing wait, and falls back to asking after repeated failures', async () => {
    w.client.start(); await w.settle(); w.last().say('hello', {});
    w.last().fail(); await w.settle();
    expect(w.client.state.mode).toBe('connecting');
    await w.advance(backoff(1)); expect(w.streams.length).toBe(2);
    for (let i = 2; i <= FAILS_BEFORE_POLL; i++) { w.last().fail(); await w.advance(backoff(i)); }
    expect(w.client.state.mode).toBe('poll');
    const asked = w.gets.length; await w.advance(1600);
    expect(w.gets.length).toBeGreaterThan(asked);                                    // the fallback keeps the picture current
    await w.advance(61_000);
    expect(w.streams.length).toBeGreaterThan(FAILS_BEFORE_POLL);                     // and the stream is tried again later
  });

  it('treats a connection that never greets as broken (a proxy holding the stream back)', async () => {
    w.client.start(); await w.settle();
    await w.advance(HELLO_MS + 10);
    expect(w.streams[0].closed).toBe(true); expect(w.posts.length).toBe(1);
    await w.advance(backoff(1)); expect(w.posts.length).toBe(2);                     // with a fresh ticket: the old one may have been the reason
  });

  it('asks for nothing while the tab is hidden and picks up where it was when it returns', async () => {
    w.client.start(); await w.settle(); w.last().say('hello', {}); w.last().say('list', listing('L3'));
    w.hide(true); expect(w.last().closed).toBe(true);
    const n = w.streams.length; const g = w.gets.length; await w.advance(60_000);
    expect([w.streams.length, w.gets.length]).toEqual([n, g]);
    w.hide(false); await w.settle();
    expect(w.streams.length).toBe(n + 1); expect(query(w.last().url).rev).toBe('L3');
  });

  it('shows a reply as it is written and lets it go once its saved message has arrived', async () => {
    w.client.start(); w.client.watch('r1'); await w.advance(50); w.last().say('hello', {});
    w.last().say('task', detail('D1', 1, [], { messages: 1 }));
    w.last().say('draft', { task: 'r1', item: 'm:1', at: 0, add: 'Hel', done: false });
    w.last().say('draft', { task: 'r1', item: 'm:1', at: 3, add: 'lo', done: true });
    expect(w.client.state.drafts.r1.text).toBe('Hello');                              // finished, but its message is not saved yet: keep showing it
    w.last().say('task', detail('D2', 1, [], { messages: 2 }));
    expect(w.client.state.drafts.r1).toBeUndefined();
  });

  it('forgets everything when it is stopped (sign-out)', async () => {
    w.client.start(); await w.settle(); w.last().say('hello', {});
    w.client.stop();
    expect(w.last().closed).toBe(true); expect(w.client.state).toMatchObject({ loaded: false, tasks: [], details: {} });
  });
});

describe('the fallback', () => {
  it('asks on a timer when the server has no gateway, sends the rev it holds, and tries the stream again much later', async () => {
    const w = world({ ticket: 404 });
    w.client.start(); w.client.watch('r1'); await w.settle();
    expect(w.client.state.mode).toBe('poll'); expect(w.streams.length).toBe(0);
    expect(w.client.state.details.r1.task.rev).toBe('D1');
    await w.advance(1500);
    expect(w.gets.some(g => g === '/v1/work?rev=L1')).toBe(true);
    expect(w.gets.some(g => g.startsWith('/v1/work/r1?after=0&rev=D1'))).toBe(true);
    w.server.list = listing('L2', [task({ phase: 'ended' })]); w.server.detail = detail('D2', 4, [{ key: 'a', first: 1, seq: 4, status: 'done' }], { phase: 'ended' });
    await w.advance(1500);
    expect(w.client.state.tasks[0].phase).toBe('ended'); expect(w.client.state.details.r1.cursor).toBe(4);
    expect(w.posts.length).toBe(1); await w.advance(5 * 60_000 + 20_000); expect(w.posts.length).toBe(2);
  });

  it('is the only transport where streams do not exist, and survives a failing request', async () => {
    const w = world({ stream: false });
    const ES = (globalThis as any).EventSource; delete (globalThis as any).EventSource;
    try {
      const c = new WorkClient({ get: async () => { throw new Error('offline'); }, post: async () => ({}) as any, hidden: () => false, onVisibility: () => () => {}, setTimeout: () => 0, clearTimeout: () => {} });
      c.start(); await w.settle();
      expect(c.state.mode).toBe('poll'); expect(c.state.tasks).toEqual([]);
    } finally { if (ES) (globalThis as any).EventSource = ES; }
  });
});
