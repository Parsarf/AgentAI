import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Organization, { type Org } from './Organization';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const org = (over: Partial<Org> = {}): Org => ({ id: 'o1', name: '', your_role: 'owner', members: [{ actor_id: '1', account_id: 'a', role: 'owner', you: true }],
  can: { 'member.role': true, 'member.remove': true, 'policy.change': true }, tool_groups: ['browser', 'files'], write_rules: ['allowed', 'admin_approval', 'blocked'],
  policy: [{ key: 'tools_allowed', plain: '', value: null, set: false }, { key: 'own_model_key', plain: '', value: null, set: false }], ...over });
const calls: { url: string; body: any }[] = [];
const server = (first: Org, after?: Org) => { calls.length = 0; vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
  if (url === '/v1/csrf') return reply({ csrf_token: 't' });
  if (init?.method === 'POST') { calls.push({ url, body: JSON.parse(String(init.body)) }); return reply({ organization: after ?? first }); }
  return reply({ organization: first }); })); };

describe('Organization', () => {
  it('an organization of one shows its owner and says each person gets their own assistant', async () => {
    server(org());
    render(<Organization />);
    expect(await screen.findByText('Owner')).toBeTruthy();
    expect(screen.getByText(/You are the only person in it/)).toBeTruthy();
    expect(screen.queryByRole('list', { name: 'Members' })).toBeNull();
  });

  it('an owner changes a role and sets what the organization decides', async () => {
    const two = org({ members: [{ actor_id: '1', account_id: 'a', role: 'owner', you: true }, { actor_id: '2', account_id: 'b', role: 'member', you: false }] });
    server(two);
    render(<Organization />);
    fireEvent.change(await screen.findByLabelText('Role of member 2'), { target: { value: 'viewer' } });
    await waitFor(() => expect(calls[0]).toEqual({ url: '/v1/organization/members/2/role', body: { role: 'viewer' } }));
    fireEvent.click(screen.getByLabelText('Browser'));
    await waitFor(() => expect(calls[1]).toEqual({ url: '/v1/organization/policy', body: { key: 'tools_allowed', value: ['files'] } }));
    fireEvent.click(screen.getByLabelText('Yes'));
    await waitFor(() => expect(calls[2]).toEqual({ url: '/v1/organization/policy', body: { key: 'own_model_key', value: false } }));
  });

  it('a member sees what is set and cannot change it', async () => {
    server(org({ your_role: 'member', can: {}, members: [{ actor_id: '1', account_id: 'a', role: 'owner', you: false }, { actor_id: '2', account_id: 'b', role: 'member', you: true }],
      policy: [{ key: 'tools_allowed', plain: '', value: ['files'], set: true }, { key: 'own_model_key', plain: '', value: false, set: true }] }));
    render(<Organization />);
    expect(await screen.findByText(/Set by your organization/)).toBeTruthy();
    expect((screen.getByLabelText('Browser') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByLabelText('Browser') as HTMLInputElement).checked).toBe(false);
    expect(screen.queryByLabelText('Role of member 1')).toBeNull();
  });
});
