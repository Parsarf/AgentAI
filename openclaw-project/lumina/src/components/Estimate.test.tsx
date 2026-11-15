import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import Estimate, { duration } from './Estimate';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const found = { kind: 'phase', based_on: 12, scope: 'yours', seconds: { typical: 300, upper: 900 }, cost_microusd: { typical: 120_000, upper: 600_000 } };

describe('Estimate', () => {
  it('words a duration for a person', () => { expect([duration(40), duration(600), duration(7200)]).toEqual(['a minute or less', '10 minutes', '2 hours']); });

  it('shows a range and says how many tasks it rests on', async () => {
    vi.stubGlobal('fetch', vi.fn(() => reply({ estimate: found })));
    render(<Estimate kind="phase" />);
    const note = await screen.findByRole('note');
    expect(note.textContent).toMatch(/Usually about 5 minutes and \$0\.12; most take no longer than 15 minutes and \$0\.6/);
    expect(note.textContent).toMatch(/Based on 12 similar tasks of yours/);
  });

  it('says when the history is from everyone', async () => {
    vi.stubGlobal('fetch', vi.fn(() => reply({ estimate: { ...found, scope: 'all', based_on: 1 } })));
    render(<Estimate kind="phase" />);
    expect((await screen.findByRole('note')).textContent).toMatch(/Based on 1 similar task from all customers/);
  });

  it('shows nothing without enough history, and nothing on an error', async () => {
    vi.stubGlobal('fetch', vi.fn(() => reply({ estimate: null })));
    const a = render(<Estimate kind="chat" />); await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(a.container.innerHTML).toBe('');
    cleanup(); vi.stubGlobal('fetch', vi.fn(() => reply({ error: 'bad' }, 400)));
    const b = render(<Estimate kind="nonsense" />); await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(b.container.innerHTML).toBe('');
  });
});
