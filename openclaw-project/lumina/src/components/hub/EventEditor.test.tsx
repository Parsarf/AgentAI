import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import EventEditor from './EventEditor';
import type { HubAccount, HubCalendar } from '../../lib/hub';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const caps = (event_write: boolean) => ({ mail: true, calendar: true, mail_search: true, incremental: true, push: false, labels: 'labels' as const, subjects: true, send: false, organize: false,
  mark_read: false, event_write, respond: false });
const account = (id: string, event_write: boolean): HubAccount => ({ id, provider: 'first', provider_label: 'First', identity: id + '@first.test', state: 'working', needs_reason: null,
  granted: { mail: true, calendar: true }, mail: null, calendar: null, capabilities: caps(event_write) });
const calendar = (connection_id: string, id: string, access: HubCalendar['access'], primary = false): HubCalendar => ({ connection_id, id, name: id, colour: 'blue', timezone: null, access,
  primary, selected: true, synced_epoch: null, filled: true, error: null, paused: false });

describe('EventEditor', () => {
  it('offers only calendars this account may change, says who will be invited, and creates once', async () => {
    const bodies: any[] = [];
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (url === '/v1/csrf') return Promise.resolve(new Response(JSON.stringify({ csrf_token: 't' })));
      bodies.push({ url, body: JSON.parse(String(init?.body)) });
      return Promise.resolve(new Response(JSON.stringify({ action: { id: 'a1', kind: 'event.create', state: 'done', preview: { title: '', summary: '', destination: '', changes: [], can_undo: true },
        verified: true, can_undo: true, undo_until_epoch: null, direct: 'calendar', ended_words: '' } })));
    }));
    const done = vi.fn();
    render(<EventEditor accounts={[account('c1', true), account('c2', false)]} calendars={[calendar('c1', 'work', 'owner', true), calendar('c1', 'shared', 'read'), calendar('c2', 'home', 'owner')]}
      day="2033-05-20" onDone={done} onCancel={() => {}} />);
    const options = Array.from(screen.getByLabelText('Calendar').querySelectorAll('option')).map(o => o.textContent);
    expect(options).toEqual(['work · c1@first.test']);                         // read-only and not-allowed calendars are not offered
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Planning' } });
    fireEvent.change(screen.getByLabelText('People'), { target: { value: 'bo@y.test, cy@z.test' } });
    expect(screen.getByRole('status').textContent).toBe('2 people will be invited by email.');
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(bodies).toEqual([{ url: '/v1/hub/events/create', body: { connection: 'c1', calendar: 'work', title: 'Planning', start: '2033-05-20T09:00', end: '2033-05-20T10:00',
      attendees: ['bo@y.test', 'cy@z.test'], notify: true } }]);
  });

  it('says so when no calendar can be changed', () => {
    render(<EventEditor accounts={[account('c1', false)]} calendars={[calendar('c1', 'work', 'owner')]} day="2033-05-20" onDone={() => {}} onCancel={() => {}} />);
    expect(screen.getByText('None of your calendars can be changed from here yet.')).toBeTruthy();
  });
});
