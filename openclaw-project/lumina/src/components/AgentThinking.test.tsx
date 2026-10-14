import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import AgentThinking from './AgentThinking';
import { api } from '../lib/api';
vi.mock('../lib/api', () => ({ api: vi.fn() }));
vi.mock('./Orb', () => ({ default: ({ state }: { state: string }) => <span data-testid="orb" data-state={state} /> }));
const task = { id: 'a', state: 'running', created_epoch: 0 };
afterEach(() => { cleanup(); vi.clearAllMocks(); });
describe('assistant thinking indicator', () => {
  it('shows an assistant orb and state without the old card or inline controls', async () => {
    vi.mocked(api).mockResolvedValue({ events: [{ sequence: 1, kind: 'activity', payload: { category: 'search', status: 'running' } }] });
    const { container, rerender } = render(<AgentThinking task={task} />);
    await screen.findByText('Searching…');
    expect(screen.getByTestId('orb').dataset.state).toBe('searching');
    expect(container.querySelector('.taskstrip')).toBeNull();
    expect(screen.queryByRole('button')).toBeNull();
    rerender(<AgentThinking task={{ ...task, state: 'completed' }} />);
    expect(screen.queryByRole('status')).toBeNull();
  });
  it('drains more than 200 events before selecting the latest activity', async () => {
    vi.mocked(api).mockImplementation(async (_method, url) => ({ events: url.includes('after=0&') ? Array.from({ length: 200 }, (_, i) => ({ sequence: i + 1, kind: 'progress' })) : [{ sequence: 201, kind: 'activity', payload: { category: 'file', status: 'running' } }] }) as any);
    render(<AgentThinking task={task} />);
    await screen.findByText('Writing…');
    expect(api).toHaveBeenCalledWith('GET', '/v1/tasks/a/events?after=200&limit=200');
  });
  it('does not let a late old task response replace the new state', async () => {
    let release!: (value: any) => void;
    vi.mocked(api).mockImplementation(async (_method, url) => url.includes('/a/') ? new Promise(resolve => { release = resolve; }) : { events: [{ sequence: 1, kind: 'activity', payload: { category: 'design', status: 'running' } }] } as any);
    const { rerender } = render(<AgentThinking task={task} />);
    await waitFor(() => expect(release).toBeDefined());
    rerender(<AgentThinking task={{ ...task, id: 'b' }} />);
    await screen.findByText('Designing…');
    release({ events: [{ sequence: 1, kind: 'activity', payload: { category: 'search', status: 'running' } }] });
    await waitFor(() => expect(screen.queryByText('Searching…')).toBeNull());
  });
  it.each([['failed', 'Something went wrong. Open Activity for details.'], ['cancelled', 'Stopped.']])('ends animation for %s', (state, text) => {
    render(<AgentThinking task={{ ...task, state }} />);
    expect(screen.getByText(text)).toBeTruthy();
    expect(screen.queryByTestId('orb')).toBeNull();
  });
});
