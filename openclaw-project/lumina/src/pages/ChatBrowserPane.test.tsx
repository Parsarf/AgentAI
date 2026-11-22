import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import Chat from './Chat';
import { clampPane, CHAT_MIN, PANE_MIN } from '../components/BrowserPane';
import { hold, resetWork, view } from '../test/workMock';
vi.mock('../state/work', async () => (await import('../test/workMock')).mock);
const data = { app: { user: { email: 'test@example.com' }, limits: { max_message_chars: 16000 }, features: { execution: true, browse: true } as Record<string, boolean> }, chats: [], refreshChats: vi.fn(async () => {}), refresh: vi.fn(async () => {}) };
vi.mock('../state/data', () => ({ useData: () => data }));
vi.mock('../components/Orb', () => ({ default: () => <span /> }));
vi.mock('../components/LiveScreen', () => ({ default: ({ enabled }: { enabled: boolean }) => <div data-testid="browser-screen" data-enabled={String(enabled)}>Browser screen</div> }));
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const Where = () => { const l = useLocation(); return <span data-testid="where">{l.pathname + l.search}</span>; };
const at = (path: string) => render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/chat/:id?" element={<><Chat /><Where /></>} /></Routes></MemoryRouter>);
const task = (over = {}) => view({ id: 't1', conversation_id: 'a', title: 'Find the paddle', label: 'Using the browser', browser: { status: 'running', live: true, host: 'shop.example' }, controls: { stop: true } as any, ...over });
beforeEach(() => {
  resetWork(); localStorage.clear(); sessionStorage.clear(); data.app.features.browse = true; Element.prototype.scrollIntoView = vi.fn(); window.scrollTo = vi.fn() as any;
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url === '/v1/csrf') return ok({ csrf_token: 't' });
    if (url === '/v1/devices') return ok({ available: false });
    if (url.startsWith('/v1/browse/')) return ok({ request_id: url.split('/')[3].split('?')[0], goal: 'Find the paddle', status: 'running', takeover: false, created_epoch: 100, url: 'https://shop.example/', events: [], pending_action: null });
    if (url.endsWith('/blocks')) return ok({ blocks: [] });
    if (url.includes('/messages')) return ok({ messages: [{ id: 1, content: 'find me a paddle', provenance: 'customer', request_id: 't1', created_at: '' }], tasks: [] });
    if (url === '/v1/files') return ok({ files: [] });
    return ok({ conversation: { id: 'a', title: 'Paddles' } });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Lumina’s browser beside the conversation', () => {
  it('opens by itself when a task of the chat has a live browser, with the conversation still beside it and an edge to size it by', async () => {
    hold(task()); at('/chat/a');
    const pane = await screen.findByRole('complementary', { name: 'Lumina’s browser' });
    expect(within(pane).getByText('shop.example')).toBeTruthy(); expect(within(pane).getByText('Live')).toBeTruthy();
    expect(await within(pane).findByTestId('browser-screen')).toBeTruthy();
    expect(await within(pane).findByRole('button', { name: /Take control/ })).toBeTruthy();          // the same controls as the task's own page
    const chat = screen.getByRole('region', { name: 'Conversation' }); expect(chat.hidden).toBe(false);
    expect(await screen.findByText('find me a paddle')).toBeTruthy();
    const edge = screen.getByRole('separator', { name: 'Resize the browser' });
    expect([edge.getAttribute('aria-valuemin'), edge.getAttribute('aria-valuenow')]).toEqual([String(PANE_MIN), '560']);
    expect(screen.queryByRole('complementary', { name: 'In this chat' })).toBeNull();                 // one panel on the right at a time
  });

  it('is sized from the keyboard, and the width is kept for next time', async () => {
    hold(task()); at('/chat/a');
    const edge = await screen.findByRole('separator', { name: 'Resize the browser' });
    fireEvent.keyDown(edge, { key: 'ArrowLeft' }); fireEvent.keyDown(edge, { key: 'ArrowLeft', shiftKey: true });         // left makes the pane on the right wider
    expect(screen.getByRole('separator').getAttribute('aria-valuenow')).toBe(String(560 + 24 + 96));
    expect((document.querySelector('.chatpage') as HTMLElement).style.getPropertyValue('--pane-w')).toBe('680px');
    fireEvent.keyDown(screen.getByRole('separator'), { key: 'Home' });
    expect(screen.getByRole('separator').getAttribute('aria-valuenow')).toBe(String(PANE_MIN));
    expect(localStorage.getItem('lumina.chat.browser-pane.width')).toBe(String(PANE_MIN));
    cleanup(); at('/chat/a');
    expect((await screen.findByRole('separator', { name: 'Resize the browser' })).getAttribute('aria-valuenow')).toBe(String(PANE_MIN));
  });

  it('never squeezes the conversation under its minimum, whatever width was asked for', () => {
    expect(clampPane(5000, 1000)).toBe(1000 - CHAT_MIN - 12); expect(clampPane(10, 1000)).toBe(PANE_MIN); expect(clampPane(600, 500)).toBe(PANE_MIN);       // 12: the edge between the two
  });

  it('hides the chat for a full view and brings it back', async () => {
    hold(task()); at('/chat/a');
    const pane = await screen.findByRole('complementary', { name: 'Lumina’s browser' });
    const toggle = within(pane).getByRole('button', { name: 'Hide chat' }); expect(toggle.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(toggle);
    expect((document.querySelector('.thread-col') as HTMLElement).hidden).toBe(true); expect(screen.queryByRole('region', { name: 'Conversation' })).toBeNull();      // out of sight and out of the tab order
    expect(screen.queryByRole('separator')).toBeNull(); expect(document.querySelector('.chatpage')!.className).toContain('pane-full');
    expect(within(pane).getByTestId('browser-screen')).toBeTruthy();                                   // the browser was not remounted: it is the same view, wider
    const back = within(pane).getByRole('button', { name: 'Show chat' }); expect(back.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(back);
    expect(screen.getByRole('region', { name: 'Conversation' }).hidden).toBe(false); expect(screen.getByRole('separator', { name: 'Resize the browser' })).toBeTruthy();
  });

  it('closes, stays closed while the task goes on, and opens again from the top of the chat', async () => {
    hold(task()); const { rerender } = at('/chat/a');
    const pane = await screen.findByRole('complementary', { name: 'Lumina’s browser' });
    fireEvent.click(within(pane).getByRole('button', { name: 'Close the browser' }));
    expect(screen.queryByRole('complementary', { name: 'Lumina’s browser' })).toBeNull();
    hold(task({ label: 'Still using the browser' }));                                                  // the task moves on: the pane the person closed does not come back by itself
    rerender(<MemoryRouter initialEntries={['/chat/a']}><Routes><Route path="/chat/:id?" element={<><Chat /><Where /></>} /></Routes></MemoryRouter>);
    expect(screen.queryByRole('complementary', { name: 'Lumina’s browser' })).toBeNull();
    const open = screen.getByRole('button', { name: /^Browser/ }); expect(open.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(open);
    expect(await screen.findByRole('complementary', { name: 'Lumina’s browser' })).toBeTruthy();
    expect(screen.getByRole('button', { name: /^Browser/ }).getAttribute('aria-pressed')).toBe('true');
  });

  it('opens for the task a link names, and closing it takes that out of the address', async () => {
    hold(task({ browser: { status: 'paused', live: false, host: 'shop.example' } }));                 // not live: it would not open by itself
    at('/chat/a?browser=t1');
    const pane = await screen.findByRole('complementary', { name: 'Lumina’s browser' });
    fireEvent.click(within(pane).getByRole('button', { name: 'Close the browser' }));
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/chat/a'));
    expect(screen.queryByRole('complementary', { name: 'Lumina’s browser' })).toBeNull();
  });

  it('is not there for a task without a browser, or where browsing is not offered', async () => {
    hold(task({ browser: null })); at('/chat/a');
    await screen.findByText('find me a paddle');
    expect(screen.queryByRole('complementary', { name: 'Lumina’s browser' })).toBeNull(); expect(screen.queryByRole('button', { name: /^Browser/ })).toBeNull();
    cleanup(); data.app.features.browse = false; hold(task()); at('/chat/a?browser=t1');
    await screen.findByText('find me a paddle');
    expect(screen.queryByRole('complementary', { name: 'Lumina’s browser' })).toBeNull(); expect(screen.queryByRole('button', { name: /^Browser/ })).toBeNull();
  });
});
