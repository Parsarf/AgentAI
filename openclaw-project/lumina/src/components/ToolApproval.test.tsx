import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import ToolApproval, { summary } from './ToolApproval';
import { api } from '../lib/api';
vi.mock('../lib/api', () => ({ api: vi.fn() }));
const call = { id: 'p1', connection_id: 'c1', tool_name: 'create_task', arguments: { name: 'Pay rent', due: 'friday', a: 1, b: 2 }, state: 'pending' };
const listing = (pending: any[]) => vi.mocked(api).mockImplementation(async (m, u) => (m === 'GET' ? { pending_calls: pending, connections: [{ id: 'c1', name: 'Asana', recipient: 'mcp.asana.com' }] } : {}) as any);
afterEach(() => { cleanup(); vi.clearAllMocks(); });
describe('ToolApproval', () => {
  it('summarises the first three arguments', () => { expect(summary(call.arguments)).toBe('name: Pay rent · due: friday · a: 1 · +1 more'); expect(summary('x')).toBe(''); });
  it('shows nothing when no call is pending', async () => { listing([]); const { container } = render(<ToolApproval active={false} onDecided={vi.fn()} />); await waitFor(() => expect(api).toHaveBeenCalled()); expect(container.textContent).toBe(''); });
  it('posts the customer\'s click to the real approval endpoint and reports it', async () => {
    listing([call]); const onDecided = vi.fn();
    render(<ToolApproval active={false} onDecided={onDecided} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Allow' }));
    await waitFor(() => expect(onDecided).toHaveBeenCalledWith(true, 'create_task'));
    expect(api).toHaveBeenCalledWith('POST', '/v1/account/mcp-approvals/p1', { approved: true });
    expect(await screen.findByText('Allowed. Continuing…')).toBeTruthy();

  });
  it('declining says nothing was run', async () => {
    listing([call]); const onDecided = vi.fn();
    render(<ToolApproval active={false} onDecided={onDecided} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(await screen.findByText('Declined. Nothing was run.')).toBeTruthy();
    expect(onDecided).toHaveBeenCalledWith(false, 'create_task');
  });
});
