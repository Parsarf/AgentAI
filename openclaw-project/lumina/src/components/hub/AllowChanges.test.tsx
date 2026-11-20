import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import AllowChanges from './AllowChanges';
import type { HubAccount } from '../../lib/hub';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const account = (missing: Record<string, string> = { event_write: 'calendar_write' }): HubAccount => ({ id: 'c1', provider: 'first', provider_label: 'First', identity: 'me@first.test',
  state: 'working', needs_reason: null, granted: { mail: true, calendar: true }, mail: null, calendar: null,
  capabilities: { mail: true, calendar: true, mail_search: true, incremental: true, push: false, labels: 'labels', subjects: true, send: false, organize: false, mark_read: false,
    event_write: false, respond: false, missing },
  grants: [{ name: 'calendar_write', capabilities: ['event_write', 'respond'], words: 'Create, change and cancel events, each time only when you approve it.' }] });

describe('AllowChanges', () => {
  it('says what the permission allows and asks for it at the provider, for this account', async () => {
    const assign = vi.fn();
    vi.stubGlobal('location', { ...window.location, assign });
    const bodies: any[] = [];
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (url === '/v1/csrf') return Promise.resolve(new Response(JSON.stringify({ csrf_token: 't' })));
      bodies.push(JSON.parse(String(init?.body)));
      return Promise.resolve(new Response(JSON.stringify({ authorize_url: 'https://provider.test/consent', expires_in: 600 })));
    }));
    render(<AllowChanges account={account()} capability="event_write" />);
    expect(screen.getByText(/each time only when you approve it/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Allow changes for me@first.test' }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith('https://provider.test/consent'));
    expect(bodies).toEqual([{ provider: 'first', connection: 'c1', add: ['calendar_write'] }]);
  });

  it('shows nothing when nothing is missing', () => {
    const { container } = render(<AllowChanges account={account({})} capability="event_write" />);
    expect(container.innerHTML).toBe('');
  });
});
