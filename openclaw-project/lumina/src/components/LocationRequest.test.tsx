import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LocationRequest from './LocationRequest';
import { api } from '../lib/api';
vi.mock('../lib/api', () => ({ api: vi.fn() }));
const mocked = vi.mocked(api);
let success: PositionCallback;
let failure: PositionErrorCallback;
let geo: ReturnType<typeof vi.fn>;
const pending = { id: 'loc1', expires_epoch: Math.floor(Date.now() / 1000) + 120 };
const flush = async () => { await act(async () => { await Promise.resolve(); await Promise.resolve(); }); };
const tick = async () => { await act(async () => { await vi.advanceTimersByTimeAsync(5000); }); };
beforeEach(() => {
  vi.useFakeTimers(); mocked.mockReset();
  Object.defineProperty(window, 'isSecureContext', { value: true, configurable: true });
  geo = vi.fn((s, f) => { success = s; failure = f; });
  Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition: geo }, configurable: true });
  mocked.mockImplementation(async (method) => method === 'GET' ? { request: pending } : { accepted: true, status: 'pending' });
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
describe('customer location handoff', () => {
  it('requests automatically once and sends actual position with accuracy', async () => {
    render(<LocationRequest />); await flush(); expect(geo).toHaveBeenCalledTimes(1);
    act(() => success({ coords: { latitude: 12, longitude: 34, accuracy: 25 } } as GeolocationPosition));
    await tick();
    expect(mocked).toHaveBeenCalledWith('POST', '/v1/location/loc1', expect.objectContaining({ action: 'respond', status: 'granted', position: { latitude: 12, longitude: 34, accuracy: 25 } }), expect.anything());
    expect(screen.queryByRole('region')).toBeNull();
  });
  it.each([[1, 'denied'], [2, 'unavailable'], [3, 'timeout']])('returns browser error %s as %s', async (code, status) => {
    render(<LocationRequest />); await flush();
    act(() => failure({ code } as GeolocationPositionError)); await tick();
    expect(mocked).toHaveBeenCalledWith('POST', '/v1/location/loc1', expect.objectContaining({ action: 'respond', status }), expect.anything());
  });
  it('does not prompt a competing tab or hidden page', async () => {
    mocked.mockImplementation(async method => method === 'GET' ? { request: pending } : { accepted: false, status: 'pending' });
    render(<LocationRequest />); await flush(); expect(geo).not.toHaveBeenCalled();
  });
  it('ignores late success after explicit refusal', async () => {
    render(<LocationRequest />); await flush();
    fireEvent.click(screen.getByText('Continue without location'));
    act(() => success({ coords: { latitude: 12, longitude: 34, accuracy: 25 } } as GeolocationPosition)); await tick();
    expect(mocked).toHaveBeenCalledWith('POST', '/v1/location/loc1', expect.objectContaining({ status: 'denied' }), expect.anything());
  });
  it('allows an explicit user gesture to retry a quiet browser permission request', async () => {
    render(<LocationRequest />); await flush(); expect(geo).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('Share my location'));
    expect(geo).toHaveBeenCalledTimes(2);
  });
  it('does not resend coordinates after unmount', async () => {
    const { unmount } = render(<LocationRequest />); await flush(); unmount();
    act(() => success({ coords: { latitude: 12, longitude: 34, accuracy: 25 } } as GeolocationPosition)); await tick();
    expect(mocked.mock.calls.filter(c => (c[2] as any)?.action === 'respond')).toHaveLength(0);
  });
  it('keeps the same answer for network retries without another permission prompt', async () => {
    let attempts = 0;
    mocked.mockImplementation(async (method, _, data: any) => {
      if (method === 'GET') return { request: pending };
      if (data.action === 'respond' && attempts++ === 0) throw new Error('offline');
      return { accepted: true, status: data.status || 'pending' };
    });
    render(<LocationRequest />); await flush(); act(() => failure({ code: 1 } as GeolocationPositionError));
    await tick(); await tick(); expect(geo).toHaveBeenCalledTimes(1); expect(attempts).toBe(2);
  });
});
