import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import LiveScreen from './LiveScreen';

vi.mock('../lib/api', () => ({ api: vi.fn().mockResolvedValue({ ticket: 'tkt', path: '/v1/live/abc/frame', expires_in: 300 }) }));

const frame = (headers: Record<string, string>, status = 200) => new Response(status === 200 ? 'x' : null, { status, headers });
const NEXT = { 'X-Seq': '1', 'X-Now-Seq': '1', 'X-By': 'jev', 'X-Mode': 'picture', 'X-Note': 'picture' };

/** A frame gateway that answers with the given responses in turn, then never answers again (so the loop stops there). */
function gateway(...answers: Response[]) {
  const urls: string[] = [];
  vi.stubGlobal('fetch', vi.fn((url: string) => { urls.push(url); const next = answers.shift(); return next ? Promise.resolve(next) : new Promise<Response>(() => {}); }));
  return urls;
}
const flush = async () => { await act(async () => { await Promise.resolve(); await Promise.resolve(); await new Promise(r => setTimeout(r, 0)); }); };
const props = { id: 'abc', enabled: true, fallback: null, interactive: false, onPoint: () => {} };

describe('the live screen', () => {
  beforeEach(() => {
    vi.stubGlobal('createImageBitmap', vi.fn().mockResolvedValue({ width: 1280, height: 800, close: () => {} }));
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: () => {} } as unknown as CanvasRenderingContext2D);      // jsdom has no canvas
  });
  afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

  it('shows who is deciding with the picture, announces a change briefly, and sends the last status it saw with the next request', async () => {
    const urls = gateway(frame(NEXT), frame({ 'X-Seq': '1', 'X-Now-Seq': '2', 'X-By': 'claude', 'X-Mode': 'controls', 'X-Note': 'took' }, 204));
    render(<LiveScreen {...props} />);
    await flush(); await flush();
    expect(urls[0]).toContain('now=0'); expect(urls[1]).toContain('now=1'); expect(urls[1]).toContain('after=1');            // the second request carries what it has already seen
    expect(screen.getByText('Claude took over this page')).toBeTruthy();                                                     // a change with no new picture still shows at once
  });

  it('settles back to a short label after the notice and shows nothing for a status it does not understand', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    gateway(frame(NEXT));
    render(<LiveScreen {...props} />);
    await act(async () => { await vi.advanceTimersByTimeAsync(10); });
    expect(screen.getByText('Looking at a picture')).toBeTruthy();
    await act(async () => { await vi.advanceTimersByTimeAsync(4100); });
    expect(screen.queryByText('Looking at a picture')).toBeNull(); expect(screen.getByText('JEV · picture')).toBeTruthy();       // the short label stays
  });

  it('does not show a status taken from anything but the four expected values', async () => {
    gateway(frame({ 'X-Seq': '1', 'X-Now-Seq': '1', 'X-By': 'jev', 'X-Mode': 'controls', 'X-Note': 'Place order now' }));
    render(<LiveScreen {...props} />);
    await flush(); await flush();
    expect(screen.queryByText('Place order now')).toBeNull(); expect(screen.queryByText('JEV')).toBeNull();
  });
});
