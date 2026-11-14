import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import McpConnections from './McpConnections';
import { api, ApiError } from '../lib/api';
vi.mock('../lib/api', () => ({ api: vi.fn(), ApiError: class extends Error { constructor(public code: string, public status: number) { super(code); } } }));
const fixture = () => ({ connections: [] as any[], presets: [{ id: 'asana', name: 'Asana', url: 'https://mcp.asana.com/v2/mcp', auth_method: 'oauth', configured: false, setup: 'Asana requires a registered MCP OAuth app.' }], pending_calls: [] as any[] });
let data: ReturnType<typeof fixture>;
beforeEach(() => {
  data=fixture();
  vi.mocked(api).mockImplementation(async (method, url, body: any) => {
    if (method === 'GET') return structuredClone(data) as any;
    if (url === '/v1/account/mcp') { data.connections.push({ id: 'c1', ...body, recipient: new URL(body.url).hostname, state: 'connecting', enabled: true, tools: [] }); delete data.connections[0].token; return { id: 'c1' } as any; }
    if (url.endsWith('/test')) { data.connections[0].state='connected'; data.connections[0].tools=[{ name: 'echo', description: '<script>untrusted()</script>', enabled: false, inputSchema: { type: 'object' } }]; return { connected: true } as any; }
    if (url.endsWith('/disconnect')) { data.connections=[]; return { provider_revocation: 'failed' } as any; }
    return {} as any;
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });
describe('MCP connections', () => {
  const addCustom = async (auth: string, extra?: () => void) => {
    fireEvent.click(await screen.findByRole('button', { name: 'Custom server' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /Custom server/ }));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'My service' } });
    fireEvent.change(screen.getByLabelText('Server URL'), { target: { value: 'https://service.example.com/mcp' } });
    fireEvent.change(screen.getByLabelText('How it signs in'), { target: { value: ({'API token': 'bearer', 'Nothing': 'none', 'Sign in': 'oauth'} as Record<string, string>)[auth] ?? auth } });
    extra?.();
  };
  it('creates a custom server, waits for discovery, clears the token and lets the user choose what each tool may do', async () => {
    const { container } = render(<McpConnections />);
    await addCustom('API token', () => fireEvent.change(screen.getByLabelText('API token'), { target: { value: 'my-private-token' } }));
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    await screen.findByText('Connected');
    expect(api).toHaveBeenCalledWith('POST', '/v1/account/mcp', { name: 'My service', url: 'https://service.example.com/mcp', auth_method: 'bearer', token: 'my-private-token' });
    expect(document.body.textContent).not.toContain('my-private-token');
    expect(container.querySelector('script')).toBeNull();
    expect(screen.getByText('<script>untrusted()</script>')).toBeTruthy();
    const group = screen.getByRole('radiogroup', { name: 'Echo: how Lumina uses it' });
    fireEvent.click(within(group).getByRole('radio', { name: 'Ask' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/account/mcp/c1/update', { tools: { echo: true }, auto: { echo: false } }));
    fireEvent.click(within(group).getByRole('radio', { name: 'Auto' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/account/mcp/c1/update', { tools: { echo: true }, auto: { echo: true } }));
  });
  it('shows what each tool is currently set to and turning one off is a single choice', async () => {
    data.connections = [{ id: 'c1', name: 'Asana', url: 'https://mcp.asana.com/v2/mcp', recipient: 'mcp.asana.com', state: 'connected', enabled: true, auth_method: 'oauth', error_code: null, tools: [
      { name: 'get_my_tasks', description: 'Your tasks', enabled: true, auto_approve: true, inputSchema: { type: 'object' } },
      { name: 'create_project', description: 'Make a project', enabled: true, auto_approve: false, inputSchema: { type: 'object' } },
      { name: 'delete_task', description: 'Remove a task', enabled: false, inputSchema: { type: 'object' } }] }];
    render(<McpConnections />); fireEvent.click(await screen.findByRole('button', { name: /^Asana, Connected/ }));
    const checked = (tool: string) => within(screen.getByRole('radiogroup', { name: `${tool}: how Lumina uses it` })).getByRole('radio', { checked: true }).textContent;
    expect(checked('Get my tasks')).toBe('Auto'); expect(checked('Create project')).toBe('Ask'); expect(checked('Delete task')).toBe('Off');
    expect(screen.getByText('2 of 3 on')).toBeTruthy();
    fireEvent.click(within(screen.getByRole('radiogroup', { name: 'Get my tasks: how Lumina uses it' })).getByRole('radio', { name: 'Off' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/account/mcp/c1/update', { tools: { get_my_tasks: false } }));
  });
  it('shows a tool the server sent but Lumina cannot use as unavailable, with the reason, while the others stay usable', async () => {
    data.connections = [{ id: 'c1', name: 'Asana', url: 'https://mcp.asana.com/v2/mcp', recipient: 'mcp.asana.com', state: 'connected', enabled: true, auth_method: 'oauth', error_code: null, tools: [
      { name: 'get_task', description: 'Read a task', enabled: false, inputSchema: { type: 'object' }, unusable: null },
      { name: 'loopy', description: 'Recursive', enabled: false, inputSchema: {}, unusable: 'its schema refers back to itself (recursive)' }] }];
    render(<McpConnections />); fireEvent.click(await screen.findByRole('button', { name: /^Asana/ }));
    await screen.findByText(/Can’t be used: its schema refers back to itself/);
    expect(screen.queryByRole('radiogroup', { name: 'Loopy: how Lumina uses it' })).toBeNull();
    fireEvent.click(within(screen.getByRole('radiogroup', { name: 'Get task: how Lumina uses it' })).getByRole('radio', { name: 'Ask' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/account/mcp/c1/update', { tools: { get_task: true }, auto: { get_task: false } }));
  });
  it('never claims Asana is ready without operator setup', async () => {
    render(<McpConnections />); fireEvent.click(await screen.findByRole('button', { name: 'Custom server' }));
    const asana = screen.getByRole('button', { name: /Asana/ });
    expect(asana.hasAttribute('disabled')).toBe(true); expect(asana.textContent).toContain('Not set up on this Lumina yet');
    expect(screen.queryByText('Connected')).toBeNull();
  });
  it('keeps discovery failures visible without displaying Connected', async () => {
    const original = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (method, url, body) => { if (url.endsWith('/test')) throw new ApiError('timeout', 409); return original(method, url, body); });
    render(<McpConnections />); await addCustom('Nothing');
    fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
    await screen.findByRole('alert'); expect(screen.queryByText('Connected')).toBeNull();
  });
  it('shows the exact arguments next to the approval and reports failed provider revocation honestly', async () => {
    data.connections = [{ id: 'c1', name: 'Service', url: 'https://service.example.com/mcp', recipient: 'service.example.com', state: 'connected', enabled: true, tools: [], auth_method: 'none' }];
    data.pending_calls = [{ id: 'p1', connection_id: 'c1', tool_name: 'create_task', state: 'pending', arguments: { title: 'Fixture task' } }];
    render(<McpConnections />); expect((await screen.findAllByText(/Fixture task/)).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/account/mcp-approvals/p1', { approved: true }));
    fireEvent.click(await screen.findByRole('button', { name: /^Service/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Disconnect' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes, disconnect' }));
    await screen.findByText(/Provider revocation failed/);
  });
  it('closes the sheet with Escape', async () => {
    data.connections = [{ id: 'c1', name: 'Service', url: 'https://service.example.com/mcp', recipient: 'service.example.com', state: 'connected', enabled: true, tools: [], auth_method: 'none' }];
    render(<McpConnections />); fireEvent.click(await screen.findByRole('button', { name: /^Service/ }));
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });
});

it('defaults to automatic detection without asking for credentials', async () => {
  render(<McpConnections />);
  fireEvent.click(await screen.findByRole('button', { name: 'Custom server' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /Custom server/ }));
  expect((screen.getByLabelText('How it signs in') as HTMLSelectElement).value).toBe('auto');
  expect(screen.queryByLabelText('API token')).toBeNull();
  fireEvent.change(screen.getByLabelText('Server URL'), { target: { value: 'https://service.example.com/mcp' } });
  fireEvent.click(screen.getByRole('button', { name: 'Connect' }));
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/account/mcp', { name: '', url: 'https://service.example.com/mcp', auth_method: 'auto' }));
});

it('opens an agent-created connection from its management link and requires address confirmation', async () => {
  window.history.replaceState({}, '', '/app/integrations?connection=c1');
  data.connections = [{ id: 'c1', name: 'Found service', url: 'https://unknown.example.com/mcp', recipient: 'unknown.example.com', auth_method: 'none', requested_auth: 'auto', added_by: 'lumina', setup_confirmed: false, state: 'confirmation_required', enabled: true, tools: [] }];
  render(<McpConnections />);
  await screen.findByText(/Added by Lumina/);
  expect((screen.getByRole('button', { name: 'Check connection' }) as HTMLButtonElement).disabled).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Confirm server address' }));
  await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/account/mcp/c1/confirm', {}));
  window.history.replaceState({}, '', '/');
});
