import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.fn();
vi.mock('./api', () => ({ api: (...args: unknown[]) => api(...args) }));
import { refreshFinished, type Message } from './conversations';

const msg = (id: number, request_id: string | null, content: string, provenance = 'agent'): Message => ({ id, request_id, provenance, content, created_at: '' });
const done = (id: string) => ({ id, state: 'completed', created_epoch: 1 });
const running = (id: string) => ({ id, state: 'running', created_epoch: 1 });
const finished = (t: { state: string }) => t.state !== 'running';

describe('re-reading a reply after its task finishes', () => {
  beforeEach(() => api.mockReset());

  it('re-reads the finished task from its first message and replaces the stale text', async () => {
    const cached = [msg(1, null, 'hi', 'customer'), msg(5, 'r1', 'ask', 'customer'), msg(6, 'r1', 'Here.\n```lumina\n{...}\n```')];
    api.mockResolvedValueOnce({ messages: [msg(5, 'r1', 'ask', 'customer'), msg(6, 'r1', 'Here.'), msg(7, 'r1', 'Checked: it.')], tasks: [] });
    const merged = await refreshFinished('c', cached, [done('r1')], new Set(), finished);
    expect(api).toHaveBeenCalledWith('GET', '/v1/conversations/c/messages?after=4');
    expect(merged?.map(m => [m.id, m.content])).toEqual([[1, 'hi'], [5, 'ask'], [6, 'Here.'], [7, 'Checked: it.']]);
  });

  it('re-reads each finished task once, never one still running, and drops the optimistic placeholder', async () => {
    const settled = new Set<string>();
    const cached = [msg(-1, 'r2', 'sending…', 'customer'), msg(8, 'r2', 'partial')];
    expect(await refreshFinished('c', cached, [running('r2')], settled, finished)).toBeNull();
    expect(api).not.toHaveBeenCalled();
    api.mockResolvedValueOnce({ messages: [msg(8, 'r2', 'final')], tasks: [] });
    const merged = await refreshFinished('c', cached, [done('r2')], settled, finished);
    expect(merged?.map(m => m.id)).toEqual([8]);
    expect(await refreshFinished('c', merged!, [done('r2')], settled, finished)).toBeNull();
    expect(api).toHaveBeenCalledTimes(1);
  });

  it('does nothing for a finished task with no cached messages', async () => {
    const settled = new Set<string>();
    expect(await refreshFinished('c', [msg(1, 'r9', 'x')], [done('r3')], settled, finished)).toBeNull();
    expect(settled.has('r3')).toBe(true); expect(api).not.toHaveBeenCalled();
  });
});
