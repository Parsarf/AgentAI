import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import YourBrowser, { handOver } from './YourBrowser';
import { api, ApiError } from '../lib/api';

vi.mock('../lib/api', async importOriginal => ({ ...await importOriginal<object>(), api: vi.fn() }));

const mac = { device_id: 'a1b2c3d4e5f60718', label: 'Chrome (mac)', created: 1_700_000_000, last_seen: 1_700_000_000, connected: false };
let devices: any[], available: boolean, pairReply: () => Promise<any>;
const calls = (method: string) => vi.mocked(api).mock.calls.filter(c => c[0] === method);

beforeEach(() => {
  devices = []; available = true; pairReply = async () => ({ code: 'ABCD2345', display: 'ABCD-2345', expires_in: 600 });
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'GET') return { available, devices } as any;
    if (path === '/v1/devices/pair') return pairReply();
    devices = devices.filter(d => !String(path).includes(d.device_id)); return { ok: true } as any;
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.useRealTimers(); delete (globalThis as any).chrome; });

describe('Your browser card', () => {
  it('stays out of the way until the account is let in, and when the service cannot be reached', async () => {
    available = false;
    const { container } = render(<YourBrowser />);
    await waitFor(() => expect(calls('GET').length).toBe(1));
    expect(container.textContent).toBe('');
    cleanup(); vi.mocked(api).mockRejectedValue(new ApiError('boom', 500));
    const again = render(<YourBrowser />); await act(async () => {});
    expect(again.container.textContent).toBe('');
  });

  it('says plainly what it does and that nothing is connected yet', async () => {
    render(<YourBrowser />);
    expect(await screen.findByRole('heading', { name: 'Your browser' })).toBeTruthy();
    expect(screen.getByText(/does not touch your other tabs/)).toBeTruthy(); expect(screen.getByText('No browser connected.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Connect a browser' })).toBeTruthy();
  });

  it('lists each browser with a text status, and removes one on request', async () => {
    devices = [mac, { ...mac, device_id: '0000000000000001', label: 'Chrome (windows)', connected: true }];
    render(<YourBrowser />);
    expect(await screen.findByText('Connected now')).toBeTruthy(); expect(screen.getByText(/^Last seen /)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Connect another browser' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Remove Chrome (mac)' }));
    await waitFor(() => expect(screen.queryByText('Chrome (mac)')).toBeNull());
    expect(calls('POST').map(c => c[1])).toEqual(['/v1/devices/a1b2c3d4e5f60718/revoke']); expect(screen.getByText('Chrome (windows)')).toBeTruthy();
  });

  it('shows the code to type when the extension cannot be reached by the page', async () => {
    render(<YourBrowser />);
    fireEvent.click(await screen.findByRole('button', { name: 'Connect a browser' }));
    const code = await screen.findByLabelText('Pairing code A B C D 2 3 4 5');
    expect(code.textContent).toBe('ABCD-2345'); expect(screen.getByText(/Type this code into the Lumina extension/)).toBeTruthy();
    expect(calls('POST')[0]).toEqual(['POST', '/v1/devices/pair', {}]);
  });

  it('asks for a new code in plain words when it is refused', async () => {
    render(<YourBrowser />); const button = await screen.findByRole('button', { name: 'Connect a browser' });
    pairReply = async () => { throw new ApiError('rate_limited', 429); }; fireEvent.click(button);
    expect((await screen.findByRole('alert')).textContent).toMatch(/Too many codes/);
    pairReply = async () => { throw new ApiError('unavailable_now', 503); }; fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/cannot reach the browser service/));
    pairReply = async () => { throw new Error('network'); }; fireEvent.click(button);
    await waitFor(() => expect(screen.getByRole('alert').textContent).toMatch(/Could not get a code/));
  });

  it('closes the code once the browser connects', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<YourBrowser />);
    fireEvent.click(await screen.findByRole('button', { name: 'Connect a browser' }));
    await screen.findByText('ABCD-2345');
    devices = [{ ...mac, connected: true }];
    await act(async () => { await vi.advanceTimersByTimeAsync(2100); });
    await waitFor(() => expect(screen.queryByText('ABCD-2345')).toBeNull());
    expect(screen.getByText('Connected now')).toBeTruthy();
  });

  it('closes the code when it runs out, and does not keep polling after the card is gone', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    pairReply = async () => ({ code: 'ABCD2345', display: 'ABCD-2345', expires_in: 4 });
    const view = render(<YourBrowser />);
    fireEvent.click(await screen.findByRole('button', { name: 'Connect a browser' })); await screen.findByText('ABCD-2345');
    await act(async () => { await vi.advanceTimersByTimeAsync(6000); });
    await waitFor(() => expect(screen.queryByText('ABCD-2345')).toBeNull());
    fireEvent.click(screen.getByRole('button', { name: 'Connect a browser' })); await screen.findByText('ABCD-2345');
    view.unmount(); const before = calls('GET').length;
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(calls('GET').length).toBe(before);
  });
});

describe('handing the code to the extension', () => {
  const runtime = (reply: any, lastError?: object) => { (globalThis as any).chrome = { runtime: { lastError, sendMessage: vi.fn((id: string, msg: any, cb: (r: any) => void) => cb(reply)) } }; return (globalThis as any).chrome.runtime.sendMessage as ReturnType<typeof vi.fn>; };

  it('sends the code and nothing else, to the extension id it was built with', async () => {
    const send = runtime({ ok: true });
    expect(await handOver('ABCD2345', 'the-extension-id')).toBe(true);
    expect(send.mock.calls[0].slice(0, 2)).toEqual(['the-extension-id', { type: 'pair', code: 'ABCD2345' }]);
  });

  it('says no when there is no id, no extension, a refusal, a runtime error, or an exception', async () => {
    runtime({ ok: true }); expect(await handOver('ABCD2345', '')).toBe(false);
    delete (globalThis as any).chrome; expect(await handOver('ABCD2345', 'id')).toBe(false);
    runtime({ ok: false, error: 'bad_code' }); expect(await handOver('ABCD2345', 'id')).toBe(false);
    runtime(undefined, { message: 'Could not establish connection' }); expect(await handOver('ABCD2345', 'id')).toBe(false);
    (globalThis as any).chrome = { runtime: { sendMessage: () => { throw new Error('nope'); } } }; expect(await handOver('ABCD2345', 'id')).toBe(false);
  });
});
