import { afterEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
    expect(options).toEqual(['work']);                                         // read-only and not-allowed calendars are not offered; a calendar goes by its own name
    expect(document.activeElement).toBe(screen.getByLabelText('Title'));       // the title comes first and has the focus
    fireEvent.change(screen.getByLabelText('Title'), { target: { value: 'Planning' } });
    fireEvent.change(screen.getByLabelText('People'), { target: { value: 'bo@y.test, cy@z.test' } });
    expect(screen.getByRole('status').textContent).toBe('2 people will be invited by email.');
    fireEvent.click(screen.getByRole('button', { name: 'Create event' }));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(bodies).toEqual([{ url: '/v1/hub/events/create', body: { connection: 'c1', calendar: 'work', title: 'Planning', start: '2033-05-20T09:00', end: '2033-05-20T10:00',
      attendees: ['bo@y.test', 'cy@z.test'], notify: true } }]);
  });

  it('is a dialog: what is wrong is said under the field it is about and nothing is sent, Esc leaves, and the focus goes back to what opened it', async () => {
    const asked = vi.fn(() => Promise.resolve(new Response('{}'))); vi.stubGlobal('fetch', asked);
    const cancel = vi.fn();
    function Page() { const [open, setOpen] = useState(false);
      return <><button type="button" onClick={() => setOpen(true)}>New event</button>
        {open && <EventEditor accounts={[account('c1', true)]} calendars={[calendar('c1', 'work', 'owner', true)]} day="2033-05-20" onDone={() => {}} onCancel={() => { cancel(); setOpen(false); }} />}</>; }
    render(<Page />);
    const opener = screen.getByRole('button', { name: 'New event' }); opener.focus(); fireEvent.click(opener);
    const dialog = screen.getByRole('dialog', { name: 'New event' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create event' }));                                // no title yet
    const title = within(dialog).getByLabelText('Title');
    expect(title.getAttribute('aria-invalid')).toBe('true');
    expect(document.getElementById(title.getAttribute('aria-describedby')!.split(' ')[0])!.textContent).toBe('Give the event a title.');
    await waitFor(() => expect(document.activeElement).toBe(title));
    fireEvent.change(title, { target: { value: 'Planning' } });
    fireEvent.change(within(dialog).getByLabelText('Ends'), { target: { value: '08:00' } });                       // before it starts
    expect(within(dialog).getByText('It must end after it starts.')).toBeTruthy();
    fireEvent.change(within(dialog).getByLabelText('People'), { target: { value: 'bo@y.test, not an address' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create event' }));
    expect(asked).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByLabelText('All day'));                                                    // an all-day event has no times to get wrong
    expect(within(dialog).queryByLabelText('Ends')).toBeNull(); expect(within(dialog).queryByText('It must end after it starts.')).toBeNull();
    expect(within(dialog).getByText('“not” is not an email address.')).toBeTruthy();
    fireEvent.keyDown(title, { key: 'Escape' });
    expect(cancel).toHaveBeenCalledTimes(1); expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('names calendars by their own name, grouped by account when there are several, and says whose the chosen one is', () => {
    const long = { ...calendar('c2', 'k9', 'owner'), name: 'Coursework: PHYS 101, ENGR 110 and ENGL 204 (Fall 2033)' };
    render(<EventEditor accounts={[account('c1', true), account('c2', true)]} calendars={[calendar('c1', 'work', 'owner', true), long]} day="2033-05-20" onDone={() => {}} onCancel={() => {}} />);
    const picker = screen.getByLabelText('Calendar') as HTMLSelectElement;
    expect(Array.from(picker.querySelectorAll('optgroup')).map(g => [g.label, Array.from(g.querySelectorAll('option')).map(o => o.textContent)])).toEqual(
      [['c1@first.test', ['work']], ['c2@first.test', ['Coursework: PHYS 101, ENGR 110 and ENGL 204 (Fall 2033)']]]);
    expect(screen.getByText('In c1@first.test')).toBeTruthy();
    fireEvent.change(picker, { target: { value: 'c2|k9' } });
    expect(screen.getByText('In c2@first.test')).toBeTruthy();
  });

  it('says so when no calendar can be changed', () => {
    render(<EventEditor accounts={[account('c1', false)]} calendars={[calendar('c1', 'work', 'owner')]} day="2033-05-20" onDone={() => {}} onCancel={() => {}} />);
    expect(screen.getByText('None of your calendars can be changed from here yet.')).toBeTruthy();
  });
});
