import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import BrowserToggle from './BrowserToggle';
import { describeOwnBrowser } from '../lib/ownBrowser';
import { api, ApiError } from '../lib/api';

vi.mock('../lib/api', async importOriginal => ({ ...await importOriginal<object>(), api: vi.fn() }));

let server: { available: boolean; use: boolean; connected: boolean; devices: any[] }, refuse: boolean;
const mac = { device_id: 'a1b2c3d4e5f60718', label: 'Chrome (mac)' };
const Where = () => { const l = useLocation(); return <p data-testid="where">{l.pathname + l.hash}</p>; };
const mount = () => render(<MemoryRouter initialEntries={['/chat/a']}><Routes><Route path="*" element={<><BrowserToggle /><Where /></>} /></Routes></MemoryRouter>);
const icon = () => screen.findByRole('button', { name: /^Use my own browser/ });
const posts = () => vi.mocked(api).mock.calls.filter(c => c[0] === 'POST');

beforeEach(() => {
  server = { available: true, use: false, connected: false, devices: [] }; refuse = false;
  vi.mocked(api).mockImplementation(async (method, path, body: any) => {
    if (method === 'GET') return { ...server } as any;
    if (path === '/v1/devices/use') { if (refuse) throw new ApiError('unavailable_now', 503); server.use = body.on; return { use: body.on } as any; }
    return {} as any;
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); });

describe('what the icon says', () => {
  it('has one plain sentence for each of the four states', () => {
    expect(describeOwnBrowser({ use: false, paired: false, connected: false })).toMatchObject({ state: 'off', label: expect.stringContaining('off') });
    expect(describeOwnBrowser({ use: true, paired: false, connected: false })).toMatchObject({ state: 'setup', label: expect.stringContaining('no browser is connected yet') });
    expect(describeOwnBrowser({ use: true, paired: true, connected: false })).toMatchObject({ state: 'waiting', label: expect.stringContaining('waiting for the Lumina extension') });
    expect(describeOwnBrowser({ use: true, paired: true, connected: true })).toMatchObject({ state: 'live', label: expect.stringContaining('run in your Chrome') });
    expect(describeOwnBrowser({ use: false, paired: true, connected: true }).state).toBe('off');           // connected but switched off: Lumina's own browser
  });
});

describe('the browser icon at the top of the chat', () => {
  it('is not there until the browser service says the feature is available', async () => {
    server.available = false;
    const { container } = mount(); await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled()); await act(async () => {});
    expect(container.querySelector('button')).toBeNull();
    cleanup(); vi.mocked(api).mockRejectedValue(new ApiError('boom', 500));
    const again = mount(); await act(async () => {}); expect(again.container.querySelector('button')).toBeNull();
  });

  it('shows off, then on, with the state in its label and aria-pressed (not only colour)', async () => {
    server.devices = [mac];
    mount(); const button = await icon();
    expect(button.getAttribute('aria-pressed')).toBe('false'); expect(button.getAttribute('title')).toBe(button.getAttribute('aria-label')); expect(button.getAttribute('data-state')).toBe('off');
    fireEvent.click(button);
    await waitFor(() => expect(button.getAttribute('aria-pressed')).toBe('true'));
    expect(posts()).toEqual([['POST', '/v1/devices/use', { on: true }]]);
    await waitFor(() => expect(button.getAttribute('data-state')).toBe('waiting')); expect(button.getAttribute('aria-label')).toMatch(/waiting for the Lumina extension/);
    expect(screen.getByTestId('where').textContent).toBe('/chat/a');                  // a browser is paired: stay on the chat
  });

  it('shows the live state with a marker when the extension is connected, and turns off again', async () => {
    server = { available: true, use: true, connected: true, devices: [mac] };
    const { container } = mount(); const button = await icon();
    expect(button.getAttribute('data-state')).toBe('live'); expect(container.querySelector('.dot.live')).not.toBeNull(); expect(button.getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(button); await waitFor(() => expect(button.getAttribute('aria-pressed')).toBe('false'));
    expect(posts()).toEqual([['POST', '/v1/devices/use', { on: false }]]);
    await waitFor(() => expect(container.querySelector('.dot.live')).toBeNull());
  });

  it('takes you to Settings to connect a browser when you switch it on and none is paired', async () => {
    mount(); fireEvent.click(await icon());
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/settings#your-browser'));
    expect(server.use).toBe(true);
  });

  it('puts the switch back and stays on the page when the server refuses', async () => {
    server.devices = [mac]; refuse = true;
    mount(); const button = await icon(); fireEvent.click(button);
    await waitFor(() => expect(posts().length).toBe(1)); await act(async () => {});
    expect(button.getAttribute('aria-pressed')).toBe('false'); expect(screen.getByTestId('where').textContent).toBe('/chat/a');
    refuse = false; fireEvent.click(button); await waitFor(() => expect(button.getAttribute('aria-pressed')).toBe('true'));
  });

  it('keeps itself fresh: picks up the extension connecting, only while the tab is visible', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    server = { available: true, use: true, connected: false, devices: [mac] };
    mount(); const button = await icon(); expect(button.getAttribute('data-state')).toBe('waiting');
    server.connected = true; await act(async () => { await vi.advanceTimersByTimeAsync(20_500); });
    await waitFor(() => expect(button.getAttribute('data-state')).toBe('live'));
    const hidden = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden'); const before = vi.mocked(api).mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(41_000); }); expect(vi.mocked(api).mock.calls.length).toBe(before); hidden.mockRestore();
  });
});
