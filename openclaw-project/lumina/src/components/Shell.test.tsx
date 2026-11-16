import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import Shell from './Shell';
import Workspace from './frame/Workspace';
import { resetWork, summary, work } from '../test/workMock';

// UI remodel (phase 1): the old shell (sidebar, top bar, right rail) became the workspace frame. These tests replace the old shell's: the decorative globe is now asked
// for by a page (Home) instead of being hidden on conversation routes, so they check the frame's rail, its counts and the phone's bottom bar.
vi.mock('../state/work', async () => (await import('../test/workMock')).mock);
let features: Record<string, unknown> = { dashboard: true, files: true, billing_mode: 'open' };
vi.mock('../state/data', () => ({ useData: () => ({ app: { user: { email: 'pat@example.com' }, features }, chats: [], refreshChats: vi.fn(), signOut: vi.fn() }) }));
vi.mock('../state/settings', () => ({ useSettings: () => ({ reducedMotion: false, setReducedMotion: vi.fn(), compact: false, setCompact: vi.fn() }) }));
vi.mock('./Backdrop', () => ({ default: () => <div data-testid="backdrop" /> }));
vi.mock('./safety/SafetyButton', () => ({ default: () => null }));

const at = (px: number) => Object.defineProperty(window, 'innerWidth', { configurable: true, value: px });
const app = (path: string) => render(<MemoryRouter initialEntries={[path]}><Routes><Route element={<Shell />}>
  <Route path="/home" element={<Workspace title="Home" backdrop><p>home</p></Workspace>} />
  <Route path="/chat/:id?" element={<Workspace title="Chat" assistant={false}><p>chat</p></Workspace>} />
  <Route path="/live/:id?" element={<Workspace title="Activity"><p>live</p></Workspace>} />
</Route></Routes></MemoryRouter>);

beforeEach(() => { localStorage.clear(); features = { dashboard: true, files: true, billing_mode: 'open' }; resetWork(); at(1280); });
afterEach(cleanup);

describe('the frame around every page', () => {
  it('has every main place one click away, in groups: Home, Chat; Inbox, Calendar, Files; Activity; Settings', () => {
    app('/home');
    const rail = screen.getByRole('navigation', { name: 'Primary' });
    const names = within(rail).getAllByRole('link').map(a => a.getAttribute('aria-label'));
    expect(names).toEqual(['Home', 'Chat', 'Inbox', 'Calendar', 'Files', 'Activity', 'Settings']);
    expect(within(rail).getByRole('link', { name: 'Home' }).getAttribute('aria-current')).toBe('page');
  });

  it('leaves out a place whose feature is off', () => {
    features = { billing_mode: 'open' }; app('/home');
    expect(within(screen.getByRole('navigation', { name: 'Primary' })).getAllByRole('link').map(a => a.getAttribute('aria-label'))).toEqual(['Home', 'Chat', 'Activity', 'Settings']);
  });

  it('shows what waits for the person as a count on Activity (the old notification bell)', () => {
    work.tasks = ['a', 'b', 'c'].map(id => summary({ id, attention: 'approval', phase: 'needs_you' })); app('/home');
    expect(screen.getByRole('link', { name: 'Activity, 3 waiting for you' })).toBeTruthy();
  });

  it('marks Chat as the place for a conversation and Activity for a task\'s live view', () => {
    app('/chat/abc');
    expect(screen.getByRole('link', { name: 'Chat' }).getAttribute('aria-current')).toBe('page');
    cleanup(); app('/live/t1');
    expect(screen.getByRole('link', { name: 'Activity' }).getAttribute('aria-current')).toBe('page');
  });

  it('shows the decorative globe only where a page asks for it, never in a conversation or a live task', () => {
    app('/home'); expect(screen.getByTestId('backdrop')).toBeTruthy(); cleanup();
    app('/chat/abc'); expect(screen.queryByTestId('backdrop')).toBeNull(); cleanup();
    app('/live/t1'); expect(screen.queryByTestId('backdrop')).toBeNull();
  });

  it('on a phone puts five entries in a bottom bar, the rest under More', () => {
    at(390); app('/home');
    const bar = screen.getByRole('navigation', { name: 'Primary' });
    expect(within(bar).getAllByRole('link').map(a => a.getAttribute('aria-label'))).toEqual(['Home', 'Chat', 'Inbox', 'Calendar']);
    fireEvent.click(within(bar).getByRole('button', { name: 'More' }));
    const more = screen.getByRole('dialog', { name: 'More' });
    expect(within(more).getAllByRole('link').map(a => a.getAttribute('aria-label'))).toEqual(['Files', 'Activity', 'Settings']);
  });

  it('offers a way past the rail straight to the page', () => {
    app('/home');
    expect(screen.getByRole('link', { name: 'Skip to content' }).getAttribute('href')).toBe('#canvas');
  });
});
