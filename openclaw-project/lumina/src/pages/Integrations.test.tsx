import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Integrations } from './Info';
import { api } from '../lib/api';
vi.mock('../lib/api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
const flags = vi.hoisted(() => ({ mcp: false, connectors: true }));
vi.mock('../state/data', () => ({ useData: () => ({ app: { features: { connectors: flags.connectors, mcp: flags.mcp } } }) }));
vi.mock('../components/McpConnections', () => ({ default: () => <p>Remote connections section</p> }));
afterEach(() => { cleanup(); vi.clearAllMocks(); flags.mcp = false; flags.connectors = true; });
const row = (service: string, label: string, state: string, identity: string | null = null) => ({ service, label, state, identity });
describe('Built-in integrations', () => {
  it('does not claim a service is connected when the API says it is not', async () => {
    vi.mocked(api).mockResolvedValue({ connections: [row('gmail', 'Gmail', 'not_connected'), row('github', 'GitHub', 'not_connected')] } as any);
    const { container } = render(<Integrations />);
    await screen.findByRole('button', { name: 'Gmail, not connected' });
    expect(screen.getByRole('button', { name: 'GitHub, not connected' })).toBeTruthy();
    expect(container.querySelector('.status-dot.success')).toBeNull();
  });
  it('marks only the services that are connected, and says who they are connected as', async () => {
    vi.mocked(api).mockResolvedValue({ connections: [row('gmail', 'Gmail', 'connected', 'me@example.com'), row('github', 'GitHub', 'not_connected')] } as any);
    render(<Integrations />);
    const gmail = await screen.findByRole('button', { name: 'Gmail, connected' });
    expect(screen.getByRole('button', { name: 'GitHub, not connected' })).toBeTruthy();
    fireEvent.click(gmail);
    expect(screen.getByText('Gmail is connected as me@example.com.')).toBeTruthy();
  });
  it('says plainly when connecting is switched off', async () => {
    vi.mocked(api).mockResolvedValue({ connections: [] } as any); flags.connectors = false;
    render(<Integrations />); fireEvent.click(await screen.findByRole('button', { name: 'Drive, not connected' }));
    expect(screen.getByText('Connecting Drive is switched off for now.')).toBeTruthy();
  });
});
describe('Remote connections section', () => {
  it('is not shown while the owner has the feature switched off', async () => {
    vi.mocked(api).mockResolvedValue({ connections: [] } as any);
    render(<Integrations />); await screen.findByRole('button', { name: 'Gmail, not connected' });
    expect(screen.queryByText('Remote connections section')).toBeNull();
    expect(screen.queryByRole('button', { name: 'Choose a service' })).toBeNull();
  });
  it('is shown once the owner has turned it on', async () => {
    flags.mcp = true; vi.mocked(api).mockResolvedValue({ connections: [] } as any);
    render(<Integrations />); expect(await screen.findByText('Remote connections section')).toBeTruthy();
  });
});
