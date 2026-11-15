import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render } from '@testing-library/react';
import { hold, resetWork, view, work } from '../test/workMock';

vi.mock('../state/work', async () => (await import('../test/workMock')).mock);
import { useActivity } from './useActivity';

const reply = (events: unknown[]) => Promise.resolve(new Response(JSON.stringify({ events }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
const Probe = ({ id }: { id: string }) => { useActivity(id, true); return null; };

beforeEach(() => { vi.useFakeTimers(); resetWork(); });
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
const eventCalls = (fetchMock: ReturnType<typeof vi.fn>) => fetchMock.mock.calls.filter(c => String(c[0]).includes('/events')).length;

describe('useActivity', () => {
  it('asks every 1.5 s while the task works when there is no push stream', async () => {
    const fetchMock = vi.fn(() => reply([])); vi.stubGlobal('fetch', fetchMock);
    work.mode = 'poll';
    render(<Probe id="r1" />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(eventCalls(fetchMock)).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(4600); });
    expect(eventCalls(fetchMock)).toBe(4);
  });

  it('with the push stream it does not poll: it asks again when the stream says the task changed', async () => {
    const fetchMock = vi.fn(() => reply([])); vi.stubGlobal('fetch', fetchMock);
    work.mode = 'stream'; hold(view({ id: 'r1', steps: 1 }));
    const { rerender } = render(<Probe id="r1" />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(eventCalls(fetchMock)).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(eventCalls(fetchMock)).toBe(1);                                      // ten quiet seconds: nothing is asked
    hold(view({ id: 'r1', steps: 2 }));                                         // the stream reports one more step
    rerender(<Probe id="r1" />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(eventCalls(fetchMock)).toBe(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(30500); });
    expect(eventCalls(fetchMock)).toBe(3);                                      // and a slow safety net
  });
});
