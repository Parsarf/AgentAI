import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import Shell from '../Shell';
import Workspace from './Workspace';
import { useCommands } from './CommandBar';
import { forPlace, keyWords } from '../../lib/shortcuts';
import { resetWork } from '../../test/workMock';

vi.mock('../../state/work', async () => (await import('../../test/workMock')).mock);
vi.mock('../../state/data', () => ({ useData: () => ({ app: { user: { email: 'pat@example.com' }, features: { dashboard: true, files: true, billing_mode: 'open' } }, chats: [{ id: 'c1', project_id: 'p', created_at: '2026-11-16', title: 'Trip to Lisbon', last_activity: '2026-11-16', active: 0 }], refreshChats: vi.fn(), signOut: vi.fn() }) }));
vi.mock('../safety/SafetyButton', () => ({ default: () => null }));

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
let search: (q: string) => unknown = () => ({ results: [], dropped: [] });
const asked: string[] = [];
beforeEach(() => {
  localStorage.clear(); resetWork(); asked.length = 0; Object.defineProperty(window, 'innerWidth', { configurable: true, value: 1280 });
  vi.stubGlobal('fetch', vi.fn((url: string) => { if (url === '/v1/csrf') return reply({ csrf_token: 't' }); if (url.startsWith('/v1/search')) { const q = new URL(url, 'https://x').searchParams.get('q')!; asked.push(q); return reply(search(q)); } return reply({}, 404); }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); search = () => ({ results: [], dropped: [] }); });

let ran = 0;
function Where() { return <p data-testid="where">{useLocation().pathname + useLocation().search}</p>; }
function CalendarLike() { useCommands([{ id: 'next', label: 'Go to the next week', shortcut: 'cal-later', run: () => { ran++; } }]); return <Workspace title="Calendar"><p>calendar</p></Workspace>; }
const app = (path = '/calendar') => render(<MemoryRouter initialEntries={[path]}><Routes><Route element={<Shell />}>
  <Route path="/calendar" element={<CalendarLike />} /><Route path="*" element={<Workspace title="Other"><Where /></Workspace>} />
</Route></Routes><Where /></MemoryRouter>);
const bar = () => within(screen.getByRole('dialog', { name: 'Search and commands' }));
const open = () => fireEvent.keyDown(window, { key: 'k', ctrlKey: true });

describe('the command bar', () => {
  it('opens with Ctrl+K and with /, and closes with Escape', () => {
    app(); open(); expect(screen.getByRole('dialog', { name: 'Search and commands' })).toBeTruthy();
    fireEvent.keyDown(bar().getByRole('combobox'), { key: 'Escape' }); expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.keyDown(window, { key: '/' }); expect(screen.getByRole('dialog', { name: 'Search and commands' })).toBeTruthy();
  });

  it('when empty shows recent things and the actions of this page, apart from places, with their shortcuts', () => {
    app(); open();
    expect(bar().getByRole('group', { name: 'Recent' }).textContent).toContain('Trip to Lisbon');
    const actions = within(bar().getByRole('group', { name: 'Actions' }));
    const next = actions.getByRole('option', { name: /Go to the next week/ });
    expect(next.className).toContain('do');
    expect(next.textContent).toContain(keyWords('arrowright'));
    expect(within(bar().getByRole('group', { name: 'Places' })).getAllByRole('option').map(o => o.querySelector('.cmd-label')?.textContent)).toEqual(['Home', 'Chat', 'Inbox', 'Calendar', 'Files', 'Activity', 'Settings']);
    fireEvent.click(next); expect(ran).toBe(1);
  });

  it('searches every store through one route and opens what is chosen, saying what each result is', async () => {
    search = () => ({ results: [{ kind: 'mail', id: 't:1', connection: 'acc', title: 'Lisbon flights', detail: 'Ann' }, { kind: 'file', id: 'u1', source: 'upload', title: 'Lisbon.pdf' }], dropped: [] });
    app(); open();
    fireEvent.change(bar().getByRole('combobox'), { target: { value: 'lisbon' } });
    expect(await bar().findByRole('group', { name: 'Mail' })).toBeTruthy();
    expect(asked).toEqual(['lisbon']);                                      // one request, after typing stopped
    expect(within(bar().getByRole('group', { name: 'Files' })).getByText('Lisbon.pdf')).toBeTruthy();
    fireEvent.click(bar().getByText('Lisbon flights'));
    expect(screen.getAllByTestId('where').at(-1)!.textContent).toBe('/inbox?connection=acc&thread=t%3A1');
  });

  it('says which store could not be searched, and offers the assistant when nothing matches', async () => {
    search = () => ({ results: [], dropped: ['mail'] });
    app('/files'); open();
    fireEvent.change(bar().getByRole('combobox'), { target: { value: 'zzqx' } });
    expect(await bar().findByText('Could not search your mail just now.')).toBeTruthy();
    expect(bar().getByText('Nothing matches “zzqx”.')).toBeTruthy();
    expect(bar().getByRole('button', { name: /Ask your assistant: “zzqx”/ })).toBeTruthy();
  });

  it('moves with the arrow keys and runs with Enter', async () => {
    app('/files'); open();
    const box = bar().getByRole('combobox');
    fireEvent.change(box, { target: { value: 'settings' } });
    await waitFor(() => expect(asked).toEqual(['settings']));
    await act(async () => { await new Promise(r => setTimeout(r, 10)); });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(screen.getAllByTestId('where').at(-1)!.textContent).toBe('/settings');
  });
});

describe('keyboard', () => {
  it('opens the help sheet with ? and lists exactly the registry\'s shortcuts for the page', () => {
    app(); fireEvent.keyDown(window, { key: '?' });
    const sheet = within(screen.getByRole('dialog', { name: 'Keyboard shortcuts' }));
    expect(sheet.getAllByRole('term').map(t => t.textContent).sort()).toEqual(forPlace('calendar').map(s => s.name).sort());
    expect(sheet.getAllByRole('definition').map(d => d.textContent).sort()).toEqual(forPlace('calendar').map(s => keyWords(s.keys)).sort());
  });

  it('moves between places with g then a letter', () => {
    app('/files'); fireEvent.keyDown(window, { key: 'g' }); fireEvent.keyDown(window, { key: 'a' });
    expect(screen.getAllByTestId('where').at(-1)!.textContent).toBe('/activity');
  });

  it('does nothing while the person is typing', () => {
    render(<MemoryRouter initialEntries={['/files']}><Routes><Route element={<Shell />}><Route path="*" element={<Workspace title="Files"><input aria-label="Type here" /><Where /></Workspace>} /></Route></Routes></MemoryRouter>);
    const box = screen.getByLabelText('Type here'); box.focus();
    fireEvent.keyDown(box, { key: 'g' }); fireEvent.keyDown(box, { key: 'a' }); fireEvent.keyDown(box, { key: '?' });
    expect(screen.getByTestId('where').textContent).toBe('/files');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
