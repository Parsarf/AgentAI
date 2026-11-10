import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import AgentResponse from '../response/AgentResponse';
import AppPlayer, { parseApplication, runnableFile } from './AppPlayer';
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });
const app = { version: 1, title: 'Calculator', runtime: 'html', code: '<button>2 + 3</button>' };
describe('application delivery', () => {
  it('validates the executable format and keeps ordinary examples literal', () => {
    expect(parseApplication(JSON.stringify(app))).toEqual(app);
    for (const value of [{ ...app, runtime: 'bash' }, { ...app, version: true }, { ...app, code: '' }, { ...app, code: 'x'.repeat(524289) }, { ...app, permissions: ['cookies'] }]) expect(parseApplication(JSON.stringify(value))).toBeNull();
    render(<AgentResponse content={'```html\n<button>Example</button>\n```'} />);
    expect(screen.queryByRole('button', { name: 'Open app' })).toBeNull();
    expect(screen.getByRole('region', { name: 'Code block' })).toBeTruthy();
  });
  it('starts only on request, isolates execution, restarts and closes', () => {
    render(<AgentResponse content={'```lumina-app\n' + JSON.stringify(app) + '\n```'} />);
    expect(document.querySelector('iframe')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Open app' }));
    const frame = document.querySelector('iframe')!;
    expect(frame.getAttribute('sandbox')).toBe('allow-scripts');
    expect(frame.getAttribute('src')).toBe('/v1/apps/player');
    fireEvent.click(screen.getByRole('button', { name: 'Restart' }));
    expect(document.querySelector('iframe')).not.toBe(frame);
    fireEvent.click(screen.getByRole('button', { name: 'Close app' }));
    expect(document.querySelector('iframe')).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Open app' }));
  });
  it('leaves malformed app manifests as code', () => {
    render(<AgentResponse content={'```lumina-app\n{"runtime":"shell"}\n```'} />);
    expect(screen.getByRole('region', { name: 'Code block' })).toBeTruthy();
  });
});

describe('app source changes and failures', () => {
  it('resets a running environment when its source or runtime changes', () => {
    const { rerender } = render(<AppPlayer app={{ ...app, version: 1, runtime: 'html' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open app' }));
    expect(document.querySelector('iframe')).toBeTruthy();
    rerender(<AppPlayer app={{ ...app, version: 1, title: 'New version', runtime: 'javascript' }} />);
    expect(document.querySelector('iframe')).toBeNull();
    expect(screen.queryByText('New version')).toBeTruthy();
  });
  it('ignores unrelated ready messages and clears a timeout after the actual player becomes ready', () => {
    vi.useFakeTimers();
    render(<AppPlayer app={{ ...app, version: 1, runtime: 'html' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open app' }));
    fireEvent(window, new MessageEvent('message', { data: { type: 'lumina.app.ready' } }));
    act(() => vi.advanceTimersByTime(20001));
    expect(screen.getByRole('alert')).toBeTruthy();
    fireEvent(window, new MessageEvent('message', { source: document.querySelector('iframe')!.contentWindow, data: { type: 'lumina.app.ready' } }));
    expect(screen.queryByRole('alert')).toBeNull();
  });
  it('shows diagnostics only from the current app frame', () => {
    render(<AppPlayer app={{ ...app, version: 1, runtime: 'html' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open app' }));
    fireEvent(window, new MessageEvent('message', { data: { type: 'lumina.app.error', message: 'unrelated' } }));
    expect(screen.queryByRole('alert')).toBeNull();
    fireEvent(window, new MessageEvent('message', { source: document.querySelector('iframe')!.contentWindow, data: { type: 'lumina.app.error', message: 'visible failure' } }));
    expect(screen.getByRole('alert').textContent).toContain('visible failure');
  });
  it('reports a missing artifact as unavailable rather than claiming the language is unsupported', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, json: async () => ({ error: 'unavailable' }) })));
    render(<AppPlayer file={{ id: 'gone', version: 1, display_name: 'calculator.py', media_type: 'text/plain', size_bytes: 12, created_at: '' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open app' }));
    expect((await screen.findByRole('alert')).textContent).toContain('no longer available');
    expect(document.querySelector('iframe')).toBeNull();
  });
  it('offers app controls only for supported nonempty files within the runtime limit', () => {
    expect(runnableFile({ display_name: 'tool.PY', size_bytes: 512 * 1024 })).toBe(true);
    expect(runnableFile({ display_name: 'tool.py', size_bytes: 512 * 1024 + 1 })).toBe(false);
    expect(runnableFile({ display_name: 'tool.py', size_bytes: 0 })).toBe(false);
    expect(runnableFile({ display_name: 'tool.ts', size_bytes: 10 })).toBe(false);
  });
  it('counts Unicode title characters consistently with the server', () => {
    expect(parseApplication(JSON.stringify({ ...app, title: '🎮'.repeat(120) }))).toBeTruthy();
    expect(parseApplication(JSON.stringify({ ...app, title: '🎮'.repeat(121) }))).toBeNull();
  });
});
