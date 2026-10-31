import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import Sidebar from './Sidebar';
import { DataProvider } from '../state/data';
import { SettingsProvider } from '../state/settings';

const app = { api_version: 't', user: { email: 'parsa@example.com', role: 'customer' }, assistant: { state: 'ready' }, limits: { max_message_chars: 100 },
  features: { chat: true, execution: true, files: false, uploads: false, telegram: false, connectors: false, billing_mode: 'open', requests: true, usage: true } };
const convs = [{ id: 'c1', project_id: 'p', created_at: new Date().toISOString(), title: 'Pickleball rackets', last_activity: new Date().toISOString(), active: 0 }];
const Where = () => <span data-testid="where">{useLocation().pathname}</span>;

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({ ok: true, status: 200, json: async () => (url === '/v1/app' ? app : url === '/v1/requests' ? { requests: [] } : url === '/v1/conversations' ? { conversations: convs } : url === '/v1/csrf' ? { csrf_token: 't' } : {}) })));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const mount = () => render(<SettingsProvider><DataProvider><MemoryRouter initialEntries={['/chat/c1']}><Sidebar /><Routes><Route path="*" element={<Where />} /></Routes></MemoryRouter></DataProvider></SettingsProvider>);

describe('Sidebar', () => {
  it('shows the menu and the chat history together, with the open chat marked', async () => {
    mount();
    expect(await screen.findByRole('link', { name: /Pickleball rackets/ })).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Home' })).toBeTruthy(); expect(screen.getByRole('link', { name: 'Settings' })).toBeTruthy();
    expect(screen.getByRole('link', { name: /Pickleball rackets/ }).getAttribute('aria-current')).toBe('page');
  });
  it('folds to an icon rail and back, remembering the choice', async () => {
    mount(); await screen.findByRole('link', { name: /Pickleball rackets/ });
    const toggle = screen.getByRole('button', { name: 'Collapse sidebar' }); expect(toggle.getAttribute('aria-expanded')).toBe('true');
    fireEvent.click(toggle);
    expect(screen.queryByRole('link', { name: /Pickleball rackets/ })).toBeNull();                   // history hidden when folded
    expect(screen.getByRole('link', { name: 'Home' })).toBeTruthy();                                // icons stay reachable
    expect(localStorage.getItem('lumina.sidebar')).toBe('0');
    expect(screen.getByRole('button', { name: 'Expand sidebar' }).getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(screen.getByRole('button', { name: 'Expand sidebar' }));
    await waitFor(() => expect(screen.getByRole('link', { name: /Pickleball rackets/ })).toBeTruthy());
    expect(localStorage.getItem('lumina.sidebar')).toBe('1');
  });
  it('starts folded when the user left it folded, and New chat goes to a blank chat', async () => {
    localStorage.setItem('lumina.sidebar', '0'); mount();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: 'New chat' }));
    expect(screen.getByTestId('where').textContent).toBe('/chat');
  });
});
