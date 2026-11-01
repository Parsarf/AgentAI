import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Live, { LiveRun } from './Live';
import { api, ApiError } from '../lib/api';
const fixture = vi.hoisted(() => ({ requests: [] as any[], rows: [] as any[], run: null as any }));
vi.mock('../state/data', () => ({ useData: () => ({ app: { features: { browse: true } }, requests: fixture.requests, refresh: vi.fn() }) }));
vi.mock('../lib/useActivity', () => ({ useActivity: () => ({ rows: fixture.rows, err: '' }) }));
vi.mock('../components/LiveScreen', () => ({ default: ({ interactive }: { interactive: boolean }) => <div data-testid="browser-screen" data-interactive={String(interactive)}>Browser screen</div> }));
vi.mock('../lib/api', async importOriginal => ({ ...await importOriginal<object>(), api: vi.fn() }));
const mount = () => render(<MemoryRouter initialEntries={['/live']}><Live /></MemoryRouter>);
beforeEach(() => {
  fixture.requests = [{ id: 'old', state: 'completed', created_epoch: 200, message: 'Older finished task' }, { id: 'active', state: 'running', created_epoch: 100, message: 'Current task', conversation_id: 'chat-a' }];
  fixture.rows = [{ key: 'c1', category: 'command', label: 'Ran a command', detail: 'echo hello', output: 'hello', status: 'running', at: '' }];
  fixture.run = null;
  Element.prototype.scrollTo = vi.fn();
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'POST') return {} as any;
    if (!fixture.run) throw new ApiError('not_found', 404);
    return fixture.run;
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });
describe('live workspace', () => {
  it('opens active work immediately instead of a task list, with real command output', async () => {
    mount();
    await screen.findByRole('log', { name: 'Terminal' });
    expect(within(screen.getByRole('log', { name: 'Terminal' })).getByText('echo hello')).toBeTruthy();
    expect(within(screen.getByRole('log', { name: 'Terminal' })).getByText('hello')).toBeTruthy();
    expect((screen.getByLabelText('Task') as HTMLSelectElement).value).toBe('active');
    expect(screen.queryByText('Watch Lumina work')).toBeNull();
    expect(screen.getByRole('link', { name: /Give Lumina guidance/ }).getAttribute('href')).toBe('/chat/chat-a');
  });
  it('shows an honest empty workspace when there are no tasks', () => {
    fixture.requests = []; mount();
    expect(screen.getByText('Your workspace is ready')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Start a task' })).toBeTruthy();
  });
  it('opens a paused browser for help and masks text entry by default', async () => {
    fixture.run = { request_id: 'active', goal: 'Current task', status: 'handoff', takeover: true, created_epoch: 100, url: 'https://example.com/login', events: [], pending_action: { label: 'Sign in' } };
    mount();
    await screen.findByText('Lumina needs your help');
    expect(screen.getByTestId('browser-screen').dataset.interactive).toBe('true');
    const input = screen.getByLabelText('Text to type into the page') as HTMLInputElement;
    expect(input.type).toBe('password');
    fireEvent.change(input, { target: { value: 'example-input' } });
    fireEvent.click(screen.getByRole('button', { name: 'Type into page' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/browse/active/control', { action: 'type', text: 'example-input' }));
    expect(input.value).toBe('');
  });
  it('waits for pending typed input before returning browser control', async () => {
    fixture.run = { request_id: 'active', goal: 'Current task', status: 'handoff', takeover: true, created_epoch: 100, events: [] };
    let finish!: () => void;
    const original = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (method, path, body) => {
      if (path.endsWith('/control')) return new Promise(resolve => { finish = () => resolve({} as any); });
      return original(method, path, body);
    });
    mount(); await screen.findByText('Lumina needs your help');
    fireEvent.change(screen.getByLabelText('Text to type into the page'), { target: { value: 'test input' } });
    fireEvent.click(screen.getByRole('button', { name: 'Type into page' }));
    await waitFor(() => expect(finish).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: 'End browser session' }));
    expect(api).not.toHaveBeenCalledWith('POST', '/v1/browse/active/release', {});
    finish();
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/browse/active/release', {}));
  });
  it('tells you why an input was refused: still working versus the take-over window having closed', async () => {
    fixture.run = { request_id: 'active', goal: 'Current task', status: 'handoff', takeover: true, created_epoch: 100, events: [] };
    const original = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (method, path, body) => {
      if (path.endsWith('/control')) throw new ApiError('not_available', 409);
      return original(method, path, body);
    });
    mount(); await screen.findByText('Lumina needs your help');
    fireEvent.change(screen.getByLabelText('Text to type into the page'), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: 'Type into page' }));
    expect(await screen.findByText('The take-over window has closed, so that input was not sent.')).toBeTruthy();
    expect(screen.queryByText(/Wait for Lumina to pause/)).toBeNull();
    cleanup(); fixture.run = { request_id: 'active', goal: 'Current task', status: 'running', takeover: false, created_epoch: 100, events: [] };
    mount(); await screen.findByRole('button', { name: 'Take control' });
    expect(screen.queryByText(/take-over window has closed/)).toBeNull();
  });
  it('does not allow browser input while the agent still owns it', async () => {
    fixture.run = { request_id: 'active', goal: 'Current task', status: 'running', takeover: false, created_epoch: 100, events: [] };
    mount();
    await screen.findByRole('button', { name: 'Take control' });
    fireEvent.click(screen.getByRole('tab', { name: 'Screen' }));
    expect(screen.getByTestId('browser-screen').dataset.interactive).toBe('false');
    expect(screen.queryByLabelText('Text to type into the page')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Take control' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/browse/active/pause', {}));
  });
});

it('explains a browser startup failure without presenting the log as a terminal', async () => {
  fixture.rows = [{ key: 'b1', category: 'browse', label: 'Used the browser', detail: 'start', output: '', status: 'failed', at: '' }];
  mount();
  await screen.findByText('Browser could not start');
  expect(screen.getByRole('log', { name: 'Activity log' })).toBeTruthy();
  expect(screen.getByRole('tab', { name: 'Activity' })).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Open chat for help' })).toBeTruthy();
});

it('does not present a failed request as a live queued browser', async () => {
  fixture.requests = [{ id: 'active', state: 'failed', message: 'Failed task', created_epoch: 100 }];
  fixture.run = { request_id: 'active', goal: 'Failed task', status: 'queued', takeover: false, created_epoch: 100, events: [] };
  mount();
  await screen.findByText('Stopped');
  expect(screen.queryByText('Starting')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Take control' })).toBeNull();
});

describe.each([false, true])('command visibility (inline=%s)', inline => {
  const view = () => <MemoryRouter><LiveRun id="active" inline={inline} /></MemoryRouter>;
  it('opens Activity, reveals real commands while running, then hides Terminal while retaining output', async () => {
    fixture.rows = [{ key: 'search', category: 'search', label: 'Searching the web', detail: 'example query', status: 'running', output: '' }];
    const { rerender } = render(view());
    await screen.findByRole('log', { name: 'Activity log' });
    expect(screen.getByRole('tab', { name: 'Activity' }).getAttribute('aria-selected')).toBe('true');
    expect(screen.queryByRole('tab', { name: 'Terminal' })).toBeNull();
    expect(screen.queryByRole('log', { name: 'Terminal' })).toBeNull();
    fixture.rows = [{ key: 'cmd', category: 'command', label: 'Ran a command', detail: 'python report.py', output: 'Preparing report', status: 'running' }];
    rerender(view());
    const terminal = await screen.findByRole('log', { name: 'Terminal' });
    expect(within(terminal).getByText('python report.py')).toBeTruthy();
    expect(within(terminal).getByText('Preparing report')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Terminal' }).getAttribute('aria-selected')).toBe('true');
    fireEvent.click(screen.getByRole('tab', { name: 'Terminal' })); // even a pinned terminal disappears after completion
    fixture.rows = [{ ...fixture.rows[0], status: 'done', output: 'Report saved' }];
    rerender(view());
    expect(screen.queryByRole('tab', { name: 'Terminal' })).toBeNull();
    expect(screen.queryByRole('log', { name: 'Terminal' })).toBeNull();
    expect(screen.getByRole('tab', { name: 'Activity' }).getAttribute('aria-selected')).toBe('true');
    const activity = screen.getByRole('log', { name: 'Activity log' });
    expect(within(activity).getByText('python report.py')).toBeTruthy();
    expect(within(activity).getByText('Report saved')).toBeTruthy();
  });
  it('hides a stale running command once the task has stopped', async () => {
    fixture.requests = [{ id: 'active', state: 'cancelled', message: 'Stopped task', created_epoch: 100 }];
    render(view());
    await screen.findByRole('log', { name: 'Activity log' });
    expect(screen.queryByRole('tab', { name: 'Terminal' })).toBeNull();
    expect(screen.queryByLabelText('running')).toBeNull();
  });
});
