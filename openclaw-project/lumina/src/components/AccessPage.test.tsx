import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import AccessPage, { length, RecentChanges, type AccessView, type Connection } from './AccessPage';

vi.mock('../state/data', () => ({ useData: () => ({ app: { features: { connector_writes: true } } }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const connection = (over: Partial<Connection> = {}): Connection => ({ id: 'c1', service: 'synthetic', label: 'Synthetic service (test only)', identity: 'test@synthetic.lumina', state: 'connected', needs_you: false,
  says: 'Can read: 2 folders. Cannot change anything.', grants: [{ resource_kind: 'folder', resource_id: 'inbox', resource_name: 'Inbox', access: 'read' }], can_be_limited: true, resource_kinds: ['folder'],
  last_used_epoch: null, freshness: [], kinds_of_change: [{ name: 'note.create', label: 'Create a note', can_undo: true, rule: 'allowed' }, { name: 'message.send', label: 'Send a message', can_undo: false, rule: 'allowed' }],
  automatic_approvals: [], allowed_by_organization: true, ...over });
const view = (over: Partial<AccessView> = {}): AccessView => ({ role: 'owner', connections: [connection()], remote_tools: [],
  tools: [{ name: 'lumina_browser', group: 'browser', allowed: true, set_by_organization: false }, { name: 'lumina_show', group: 'display', allowed: true, set_by_organization: false }],
  saved_logins: [{ kind: 'login', label: 'shop.example', site: 'shop.example' }], model_key: { host: 'api.example.com', hint: 'ab12' }, own_model_key_allowed: true, memory: { count: 3, where: 'Settings, Memory' },
  acts_without_you: [], waits: [{ kind: 'action_approval', label: 'Approving a change in a connected service', seconds: 259200 }, { kind: 'browser_takeover', label: 'You driving the browser', seconds: 1800 }], set_by_organization: [], ...over });
const calls: { url: string; body: any }[] = [];
const server = (routes: Record<string, unknown>) => { calls.length = 0; vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
  if (url === '/v1/csrf') return reply({ csrf_token: 't' });
  if (init?.method === 'POST') calls.push({ url, body: JSON.parse(String(init.body)) });
  const key = Object.keys(routes).find(k => url === k || (init?.method === 'POST' && k === 'POST ' + url));
  return key ? reply(routes[init?.method === 'POST' && routes['POST ' + url] !== undefined ? 'POST ' + url : key]) : reply({ actions: [], available: [] }); })); };

describe('AccessPage', () => {
  it('says in a sentence what each connection can reach, exactly as the server gives it', async () => {
    server({ '/v1/controls': view(), '/v1/integrations': { available: [] } });
    render(<AccessPage />);
    expect(await screen.findByText('Can read: 2 folders. Cannot change anything.')).toBeTruthy();
    expect(screen.getByText('Not used yet.')).toBeTruthy();
    expect(screen.getByText('shop.example')).toBeTruthy();
    expect(screen.getByText('api.example.com, key ending ab12')).toBeTruthy();                      // the host and the last four characters, never the key
    expect(screen.getByText('3 notes (Settings, Memory)')).toBeTruthy();
    expect(screen.getByText('Approving a change in a connected service: 3 days. Then it ends and nothing is done.')).toBeTruthy();
    expect(screen.getByText('You driving the browser: 30 minutes. Then it ends and nothing is done.')).toBeTruthy();
  });

  it('shows when a connection needs you and what an organization switched off', async () => {
    server({ '/v1/controls': view({ connections: [connection({ needs_you: true, state: 'reconnect_required' })], own_model_key_allowed: false,
      tools: [{ name: 'lumina_browser', group: 'browser', allowed: false, set_by_organization: true }] }), '/v1/integrations': { available: [] } });
    render(<AccessPage />);
    expect(await screen.findByText('Needs you: reconnect it')).toBeTruthy();
    expect(screen.getByText(/switched off by your organization/)).toBeTruthy();
    expect(screen.getByText('Not allowed by your organization')).toBeTruthy();
  });

  it('nothing is ticked until the customer ticks it, and "everything" is its own choice', async () => {
    const saved = connection({ says: 'Can read: every folder. Cannot change anything.', grants: [{ resource_kind: 'folder', resource_id: '*', resource_name: '', access: 'read' }] });
    server({ '/v1/controls': view({ connections: [connection({ grants: [], says: 'Can read: nothing yet (nothing has been chosen). Cannot change anything.' })] }), '/v1/integrations': { available: [] },
      '/v1/integrations/c1/resources': { resources: [{ kind: 'folder', id: 'inbox', name: 'Inbox' }, { kind: 'folder', id: 'archive', name: 'Archive' }] }, 'POST /v1/integrations/c1/grants': { connection: saved } });
    render(<AccessPage />);
    fireEvent.click(await screen.findByText('Choose what it can reach'));
    const picker = await screen.findByRole('group', { name: /may reach/ });
    const boxes = within(picker).getAllByRole('checkbox') as HTMLInputElement[];
    expect(boxes.every(b => !b.checked)).toBe(true);
    fireEvent.click(within(picker).getByLabelText(/Everything/));
    expect(within(picker).queryByLabelText('Inbox')).toBeNull();                                    // the single items make no sense beside "everything"
    fireEvent.click(within(picker).getByText('Save what it can reach'));
    await waitFor(() => expect(screen.getByText('Can read: every folder. Cannot change anything.')).toBeTruthy());
    expect(calls[0]).toEqual({ url: '/v1/integrations/c1/grants', body: { grants: [{ kind: 'folder', id: '*', access: 'read', name: '' }] } });
  });

  it('going ahead without asking is never ticked by default, and says so for what cannot be taken back', async () => {
    server({ '/v1/controls': view(), '/v1/integrations': { available: [] }, 'POST /v1/integrations/c1/auto-approve': { automatic_approvals: [{ kind: 'message.send', include_irreversible: true }] } });
    render(<AccessPage />);
    fireEvent.click(await screen.findByText('Changes it can prepare (2)'));
    const plain = screen.getByLabelText('Go ahead without asking me') as HTMLInputElement;
    const risky = screen.getByLabelText('Go ahead without asking me, even though it cannot be taken back') as HTMLInputElement;
    expect(plain.checked || risky.checked).toBe(false);
    fireEvent.click(risky);
    await waitFor(() => expect(calls[0]).toEqual({ url: '/v1/integrations/c1/auto-approve', body: { kind: 'message.send', enabled: true, include_irreversible: true } }));
  });

  it('removing asks once more and then ends the connection', async () => {
    server({ '/v1/controls': view(), '/v1/integrations': { available: [] }, 'POST /v1/integrations/c1/remove': { removed: true } });
    render(<AccessPage />);
    fireEvent.click(await screen.findByText('Remove'));
    expect(screen.getByText('Remove it? Its access ends at once.')).toBeTruthy();
    expect(calls.length).toBe(0);
    fireEvent.click(screen.getByText('Yes, remove'));
    await waitFor(() => expect(calls[0].url).toBe('/v1/integrations/c1/remove'));
  });

  it('words a wait in days or minutes', () => {
    expect(length(86400)).toBe('1 day'); expect(length(259200)).toBe('3 days'); expect(length(1800)).toBe('30 minutes');
  });
});

describe('RecentChanges', () => {
  const change = (over: Record<string, unknown> = {}) => ({ id: 'a1', state: 'done', preview: { summary: 'Create the note "Plan"', destination: 'Synthetic service' }, can_undo: true,
    undo_until_epoch: Math.floor(Date.now() / 1000) + 600, compensations: [], verified: true, verify_note: '', ended_words: '', executed_epoch: Math.floor(Date.now() / 1000) - 60, undo_of: null, compensates: null, ...over });
  it('offers undo while it is still possible, and a correction where there is no undo', async () => {
    server({ '/v1/actions': { actions: [change(), change({ id: 'a2', preview: { summary: 'Send a message to sam', destination: 'To sam' }, can_undo: false, undo_until_epoch: null, compensations: ['message.correction'] }),
      change({ id: 'a3', preview: { summary: 'Old change', destination: 'x' }, undo_until_epoch: 1 })] }, 'POST /v1/actions/a1/undo': { action: {} } });
    render(<RecentChanges />);
    expect(await screen.findByText('Create the note "Plan"')).toBeTruthy();
    expect(screen.getAllByText('Undo').length).toBe(1);                                             // the one whose time has passed offers nothing
    expect(screen.getByText('Send a correction')).toBeTruthy();
    fireEvent.click(screen.getByText('Undo'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('waiting for your approval'));
    expect(calls[0]).toEqual({ url: '/v1/actions/a1/undo', body: {} });
  });
  it('shows a result that did not match what was sent', async () => {
    server({ '/v1/actions': { actions: [change({ verified: false, verify_note: 'what is there differs from what was sent' })] } });
    render(<RecentChanges />);
    expect((await screen.findByRole('note')).textContent).toContain('differs from what was sent');
  });
});
