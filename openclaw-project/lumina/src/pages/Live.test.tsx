import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import Live from './Live';
import { api, ApiError } from '../lib/api';
import { hold, resetWork, row, summary, view, work } from '../test/workMock';
const fixture = vi.hoisted(() => ({ run: null as any }));
vi.mock('../state/data', () => ({ useData: () => ({ app: { features: { browse: true } } }) }));
vi.mock('../state/work', async () => (await import('../test/workMock')).mock);
vi.mock('../components/Orb', () => ({ default: () => <span data-testid="orb" /> }));
vi.mock('../components/LiveScreen', () => ({ default: ({ interactive, enabled }: { interactive: boolean; enabled: boolean }) => <div data-testid="browser-screen" data-interactive={String(interactive)} data-enabled={String(enabled)}>Browser screen</div> }));
vi.mock('../lib/api', async importOriginal => ({ ...await importOriginal<object>(), api: vi.fn() }));
const Where = () => <span data-testid="where">{useLocation().pathname}</span>;
const mount = (path = '/live/active') => render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/live/:id?" element={<Live />} /><Route path="*" element={<Where />} /></Routes></MemoryRouter>);
const browsing = (over = {}) => hold(view({ id: 'active', conversation_id: 'chat-a', title: 'Current task', label: 'Using the browser', browser: { status: 'running', live: true, host: 'example.com' }, controls: { stop: true } as any, ...over }),
  [row({ key: 'b1', category: 'browse', label: 'Used the browser', detail: 'example.com', status: 'running', ended_at: null })]);
beforeEach(() => {
  resetWork(); fixture.run = null; Element.prototype.scrollTo = vi.fn();
  vi.mocked(api).mockImplementation(async method => { if (method === 'POST') return {} as any; if (!fixture.run) throw new ApiError('not_found', 404); return fixture.run; });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const run = (over: object) => ({ request_id: 'active', goal: 'Current task', status: 'running', takeover: false, created_epoch: 100, url: 'https://example.com/login', events: [], pending_action: null, ...over });

describe('where /live goes', () => {
  it('is not a destination of its own: it opens the task that is going on, or Activity when nothing is', async () => {
    work.tasks = [summary({ id: 'held', title: 'A held one', phase: 'paused' }), summary({ id: 'done', phase: 'ended', outcome: 'completed' }), summary({ id: 'active' })];      // a held task is open too, but it is not what is going on
    mount('/live');
    expect(await screen.findByText('Compare two laptops')).toBeTruthy();                     // the open task's workspace
    cleanup(); work.tasks = [summary({ id: 'done', phase: 'ended', outcome: 'completed' })];
    mount('/live');
    expect((await screen.findByTestId('where')).textContent).toBe('/tasks');
  });
  it('says so when the task does not exist', async () => { mount('/live/nope'); expect(await screen.findByRole('alert')).toBeTruthy(); });
});

describe('a task without a browser', () => {
  it('is its record: what it is doing, the timeline with real command output, and how to steer it. Nothing probes for a browser', async () => {
    hold(view({ id: 'active', conversation_id: 'chat-a', title: 'Current task', label: 'Running a command', controls: { stop: true } as any }),
      [row({ key: 'c1', category: 'command', label: 'Ran a command', detail: 'echo hello', output: 'hello', status: 'running', ended_at: null })]);
    mount();
    expect(await screen.findByText('echo hello')).toBeTruthy(); expect(screen.getByText('hello')).toBeTruthy(); expect(screen.getByText('in progress')).toBeTruthy();
    expect(screen.queryByTestId('browser-screen')).toBeNull();
    expect(vi.mocked(api).mock.calls.some(c => String(c[1]).startsWith('/v1/browse/'))).toBe(false);
    expect(screen.getByRole('link', { name: 'send a message in the chat' }).getAttribute('href')).toBe('/chat/chat-a');
    fireEvent.click(screen.getByRole('button', { name: 'Stop' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/requests/active/cancel', {}));
  });
  it('does not show a call as in progress once the task is over', async () => {
    hold(view({ id: 'active', state: 'failed', phase: 'ended', label: 'Failed', tone: 'bad', outcome: 'failed', verification: 'unverified', note: 'The run ended with an error before it finished.', controls: { retry: true } as any }),
      [row({ key: 'c1', category: 'command', label: 'Ran a command', detail: 'sleep 99', status: 'running', ended_at: null })]);
    mount();
    expect(await screen.findByText('no result was recorded')).toBeTruthy(); expect(screen.queryByText('in progress')).toBeNull();
    expect(screen.getByText('The run ended with an error before it finished.')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy(); expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull();
  });
});

describe('a task with a browser', () => {
  it('offers Take control while Lumina drives, and no input reaches the page until it has paused', async () => {
    browsing(); fixture.run = run({});
    mount();
    fireEvent.click(await screen.findByRole('button', { name: 'Take control' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/browse/active/pause', {}));
    expect(screen.getByTestId('browser-screen').dataset.interactive).toBe('false');
    expect(screen.queryByLabelText('Text to type into the page')).toBeNull();
  });
  it('opens a handed-over browser for help and masks typed text by default', async () => {
    browsing({ phase: 'needs_you', label: 'Waiting for you in the browser', tone: 'attention' }); fixture.run = run({ status: 'handoff', takeover: true, pending_action: { label: 'Sign in' } });
    mount();
    await screen.findByText('Lumina needs your help'); expect(screen.getByText(/Lumina stopped before: Sign in/)).toBeTruthy();
    expect(screen.getByTestId('browser-screen').dataset.interactive).toBe('true');
    const input = screen.getByLabelText('Text to type into the page') as HTMLInputElement;
    expect(input.type).toBe('password');
    fireEvent.change(input, { target: { value: 'example-input' } });
    fireEvent.click(screen.getByRole('button', { name: 'Type into page' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/browse/active/control', { action: 'type', text: 'example-input' }));
    expect(input.value).toBe('');
  });
  it('says what Lumina is waiting for and lets the run carry on', async () => {
    browsing(); fixture.run = run({ status: 'paused', takeover: true, needs_you: 'This page needs you to sign in.' });
    mount();
    expect(await screen.findByText(/This page needs you to sign in\./)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'I’m done, continue' }));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/browse/active/resume', {}));
  });
  it('waits for typed input to be sent before handing the browser back', async () => {
    browsing(); fixture.run = run({ status: 'handoff', takeover: true });
    let finish!: () => void; const original = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (method, path, body) => (String(path).endsWith('/control') ? new Promise(resolve => { finish = () => resolve({} as any); }) : original(method, path, body)));
    mount(); await screen.findByText('Lumina needs your help');
    fireEvent.change(screen.getByLabelText('Text to type into the page'), { target: { value: 'test input' } });
    fireEvent.click(screen.getByRole('button', { name: 'Type into page' }));
    await waitFor(() => expect(finish).toBeDefined());
    fireEvent.click(screen.getByRole('button', { name: 'End browser session' }));
    expect(api).not.toHaveBeenCalledWith('POST', '/v1/browse/active/release', {});
    finish();
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/browse/active/release', {}));
  });
  it('says why an input was refused', async () => {
    browsing(); fixture.run = run({ status: 'handoff', takeover: true });
    const original = vi.mocked(api).getMockImplementation()!;
    vi.mocked(api).mockImplementation(async (method, path, body) => { if (String(path).endsWith('/control')) throw new ApiError('not_available', 409); return original(method, path, body); });
    mount(); await screen.findByText('Lumina needs your help');
    fireEvent.change(screen.getByLabelText('Text to type into the page'), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: 'Type into page' }));
    expect(await screen.findByText('The take-over window has closed, so that input was not sent.')).toBeTruthy();
  });
  it('is a record once the task is over: no live picture, no controls, the last saved picture if there is one', async () => {
    browsing({ state: 'completed', phase: 'ended', label: 'Done · not confirmed', tone: 'unsure', outcome: 'completed', verification: 'unverified', browser: { status: 'done', live: false, host: 'example.com' }, controls: {} as any });
    fixture.run = run({ status: 'running', events: [{ n: 1, kind: 'screenshot', file: 's1.jpg' }] });       // a stale "running" from the browser service must not revive a finished task
    mount();
    await screen.findByText(/The last picture saved for this task/);
    expect(screen.getByTestId('browser-screen').dataset.enabled).toBe('false');
    expect(screen.queryByRole('button', { name: 'Take control' })).toBeNull(); expect(screen.queryByRole('button', { name: 'Stop' })).toBeNull();
    expect(screen.getByText('Done · not confirmed')).toBeTruthy();
  });
  it('puts a permission prompt at the top of the workspace', async () => {
    browsing({ phase: 'needs_you', label: 'Waiting for your permission', tone: 'attention', needs: [{ kind: 'approval', id: 'call1', tool: 'send_email', service: 'Gmail', arguments: { to: 'a@b.c' }, expires_epoch: 9e9 }] });
    fixture.run = run({});
    mount();
    expect(await screen.findByRole('group', { name: 'Permission to use Send email' })).toBeTruthy();
  });
});
