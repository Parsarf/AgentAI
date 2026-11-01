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
  it('creates a custom server, waits for discovery, clears the token and lets the user enable tools', async () => {
    const { container }=render(<McpConnections />);
    fireEvent.click(await screen.findByRole('button', { name: 'Add custom server' }));
    fireEvent.change(screen.getByLabelText('Connection name'), { target: { value: 'My service' } });
    fireEvent.change(screen.getByLabelText('Server URL'), { target: { value: 'https://service.example.com/mcp' } });
    fireEvent.change(screen.getByLabelText('Authentication'), { target: { value: 'bearer' } });
    fireEvent.change(screen.getByLabelText('Bearer API token'), { target: { value: 'my-private-token' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect and discover tools' }));
    await screen.findByText('Connected');
    expect(api).toHaveBeenCalledWith('POST','/v1/account/mcp',{ name: 'My service', url: 'https://service.example.com/mcp', auth_method: 'bearer', token: 'my-private-token' });
    expect(container.textContent).not.toContain('my-private-token');
    expect(container.querySelector('script')).toBeNull();
    expect(screen.getByText('<script>untrusted()</script>')).toBeTruthy();
    fireEvent.click(screen.getByRole('switch', { name: 'echo' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST','/v1/account/mcp/c1/update',{ tools: { echo: true } }));
  });
  it('shows Asana registration requirements and never claims OAuth is ready without operator setup', async () => {
    render(<McpConnections />);fireEvent.click(await screen.findByRole('button', { name: 'Choose a service' }));
    expect(screen.getByDisplayValue('https://mcp.asana.com/v2/mcp')).toBeTruthy();
    expect(screen.getByText(/OAuth setup is not available/)).toBeTruthy();
    expect(screen.queryByText('Connected')).toBeNull();
  });
  it('keeps discovery failures visible without displaying Connected', async () => {
    const original=vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (method,url,body) => { if (url.endsWith('/test')) throw new ApiError('timeout',409); return original(method,url,body); });
    render(<McpConnections />);fireEvent.click(await screen.findByRole('button', { name: 'Add custom server' }));
    fireEvent.change(screen.getByLabelText('Connection name'),{target:{value:'Slow service'}});
    fireEvent.change(screen.getByLabelText('Server URL'),{target:{value:'https://service.example.com/mcp'}});
    fireEvent.change(screen.getByLabelText('Authentication'),{target:{value:'none'}});
    fireEvent.click(screen.getByRole('button',{name:'Connect and discover tools'}));
    await screen.findByRole('alert');expect(screen.queryByText('Connected')).toBeNull();
  });
  it('requires a customer decision for the exact tool arguments and reports failed provider revocation honestly', async () => {
    data.connections=[{id:'c1',name:'Service',url:'https://service.example.com/mcp',recipient:'service.example.com',state:'connected',enabled:true,tools:[],auth_method:'none'}];
    data.pending_calls=[{id:'p1',connection_id:'c1',tool_name:'create_task',state:'pending',arguments:{title:'Fixture task'}}];
    render(<McpConnections />);await screen.findByText('Fixture task',{exact:false});
    fireEvent.click(screen.getByRole('button',{name:'Approve this exact call'}));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST','/v1/account/mcp-approvals/p1',{approved:true}));
    fireEvent.click(within(screen.getByRole('article',{name:'Service'})).getByRole('button',{name:'Disconnect'}));
    await screen.findByText(/Provider revocation failed/);
  });
});
