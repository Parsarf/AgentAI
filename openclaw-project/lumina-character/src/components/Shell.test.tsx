import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Shell from './Shell';
vi.mock('../state/data', () => ({ useData: () => ({ requests: [], chats: [], refreshChats: vi.fn() }) }));
vi.mock('../state/settings', () => ({ useSettings: () => ({ sidebarOpen: true, reducedMotion: false, setReducedMotion: vi.fn(), setSidebarOpen: vi.fn() }) }));
vi.mock('./Rail', () => ({ default: () => <p>Workspace details</p> }));
vi.mock('./Sidebar', async importOriginal => ({ ...await importOriginal<typeof import('./Sidebar')>(), default: ({ onMore }: { onMore(): void }) => <button onClick={onMore}>More pages</button> }));
vi.mock('./Backdrop', () => ({ default: () => <div data-testid="backdrop" /> }));
afterEach(cleanup);
describe('conversation background', () => {
  it('hides decorative scenery in an active conversation', () => {
    render(<MemoryRouter initialEntries={['/chat/example']}><Shell /></MemoryRouter>);
    expect(screen.queryByTestId('backdrop')).toBeNull();
  });
  it.each(['/chat', '/home'])('retains scenery on %s', path => {
    render(<MemoryRouter initialEntries={[path]}><Shell /></MemoryRouter>);
    expect(screen.getByTestId('backdrop')).toBeTruthy();
  });
});

it('keeps the live workspace free of background scenery', () => {
  render(<MemoryRouter initialEntries={['/live']}><Shell /></MemoryRouter>);
  expect(screen.queryByTestId('backdrop')).toBeNull();
});

it('keeps workspace activity optional and lets the user open and close it', () => {
  render(<MemoryRouter initialEntries={['/home']}><Shell /></MemoryRouter>);
  const toggle = screen.getByRole('button', { name: 'Activity' });
  expect(toggle.getAttribute('aria-expanded')).toBe('false');
  expect(screen.queryByRole('complementary', { name: 'Workspace activity' })).toBeNull();
  fireEvent.click(toggle);
  expect(toggle.getAttribute('aria-expanded')).toBe('true');
  expect(screen.getByRole('complementary', { name: 'Workspace activity' })).toBeTruthy();
  fireEvent.click(toggle);
  expect(screen.queryByText('Workspace details')).toBeNull();
});

it('opens all pages from mobile navigation and restores keyboard focus on Escape', () => {
  render(<MemoryRouter initialEntries={['/chat/example']}><Shell /></MemoryRouter>);
  const opener = screen.getByRole('button', { name: 'More pages' });
  opener.focus(); fireEvent.click(opener);
  const menu = screen.getByRole('dialog', { name: 'Pages' });
  const close = within(menu).getByRole('button', { name: 'Close' });
  expect(document.activeElement).toBe(close);
  expect(within(menu).getAllByRole('link')).toHaveLength(10);
  fireEvent.keyDown(window, { key: 'Tab', shiftKey: true });
  expect(document.activeElement).toBe(within(menu).getByRole('link', { name: 'Settings' }));
  fireEvent.keyDown(window, { key: 'Escape' });
  expect(screen.queryByRole('dialog', { name: 'Pages' })).toBeNull();
  expect(document.activeElement).toBe(opener);
});
