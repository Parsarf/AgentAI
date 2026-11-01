import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { Integrations } from './Info';
import { api } from '../lib/api';
vi.mock('../lib/api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
const flags = vi.hoisted(() => ({ mcp: false }));
vi.mock('../state/data', () => ({ useData: () => ({ app: { features: { connectors: true, mcp: flags.mcp } } }) }));
vi.mock('../components/McpConnections', () => ({ default: () => <p>Remote connections section</p> }));
afterEach(() => { cleanup(); vi.clearAllMocks(); flags.mcp = false; });
const row = (service: string, label: string, state: string, identity: string | null = null) => ({ service, label, state, identity });
describe('Integrations service list', () => {
  it('does not claim a service is connected when the API says it is not', async () => {
    vi.mocked(api).mockResolvedValue({ connections: [row('gmail', 'Gmail', 'not_connected'), row('github', 'GitHub', 'not_connected')] } as any);
    render(<Integrations />);
    await screen.findByText('No services connected.');
    expect(screen.queryByText(/connected$/)).toBeNull();
  });
  it('names only the services that are connected', async () => {
    vi.mocked(api).mockResolvedValue({ connections: [row('gmail', 'Gmail', 'connected', 'me@example.com'), row('github', 'GitHub', 'not_connected')] } as any);
    render(<Integrations />);
    await waitFor(() => expect(screen.getByText('Gmail · connected as me@example.com')).toBeTruthy());
    expect(screen.queryByText(/GitHub/)).toBeNull();
  });
});
describe('Remote connections section', () => {
  it('is not shown while the owner has the feature switched off', async () => {
    vi.mocked(api).mockResolvedValue({ connections: [] } as any);
    render(<Integrations />); await screen.findByText('No services connected.');
    expect(screen.queryByText('Remote connections section')).toBeNull();
  });
  it('is shown once the owner has turned it on', async () => {
    flags.mcp = true; vi.mocked(api).mockResolvedValue({ connections: [] } as any);
    render(<Integrations />); expect(await screen.findByText('Remote connections section')).toBeTruthy();
  });
});
