import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import BlockView from './BlockView';
import { DataProvider } from '../../state/data';
import type { Block } from '../../lib/genui/schema';

const app = { api_version: 't', user: { email: 'a@b.co', role: 'customer' }, assistant: { state: 'ready' }, limits: { max_message_chars: 100 },
  features: { chat: true, execution: true, files: false, uploads: false, telegram: false, connectors: false, billing_mode: 'open', requests: true, usage: true } };

const formSpec = { schemaVersion: '1.0', type: 'form', title: 'Shape your website', submit: { label: 'Create the plan', action: 'submit_requirements' }, fields: [
  { id: 'kind', type: 'segmented', label: 'What kind?', required: true, default: 'business', options: [{ label: 'Business', value: 'business' }, { label: 'E-commerce', value: 'ecommerce' }] },
  { id: 'payments', type: 'select', label: 'Payment provider', default: 'stripe', showIf: { field: 'kind', equals: 'ecommerce' }, options: [{ label: 'Stripe', value: 'stripe' }, { label: 'PayPal', value: 'paypal' }] },
  { id: 'accounts', type: 'toggle', label: 'User accounts', default: false }] };
const ph = (id: string, deps: string[] = [], extra = {}) => ({ id, title: id[0].toUpperCase() + id.slice(1), description: '', enabled: true, optional: false, requiresApproval: false, dependsOn: deps, ...extra });
const planSpec = { schemaVersion: '1.0', type: 'task_plan', title: 'Website plan', phases: [ph('analyze'), ph('build', ['analyze']), ph('test', ['build'])] };

const done = (summary = 'finished') => ({ state: 'completed' as const, attempts: 1, request_id: 'r', summary, approved: false, started_epoch: 1, finished_epoch: 2 });
const pend = () => ({ state: 'pending' as const, attempts: 0, request_id: null, summary: null, approved: false, started_epoch: null, finished_epoch: null });
const mk = (kind: 'form' | 'task_plan', spec: any, state: any, extra: Partial<Block> = {}): Block => ({ id: 'blk1', conversation_id: 'c', anchor_message_id: 1, kind, schema_version: '1.0', spec, state, version: 1, status: 'draft', launched_request_id: null, ...extra });

let calls: { url: string; body?: any }[] = [];
beforeEach(() => {
  calls = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: any = {}) => {
    calls.push({ url, body: init.body ? JSON.parse(init.body) : undefined });
    const ok = (b: any, status = 200) => ({ ok: status < 400, status, json: async () => b });
    if (url === '/v1/csrf') return ok({ csrf_token: 't' }); if (url === '/v1/app') return ok(app); if (url === '/v1/requests') return ok({ requests: [] }); if (url === '/readyz') return ok({});
    if (url.endsWith('/state') || url.endsWith('/live')) return ok({ block: { version: JSON.parse(init.body).version + 1 } });
    if (url.endsWith('/phase') || url.endsWith('/stop')) return ok({ block: {} });
    if (url.endsWith('/submit') || url.endsWith('/launch')) return ok({ request: { id: 'r1' }, block: {} }, 202);
    return ok({}, 404);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.useRealTimers(); });

const view = (b: Block, onChanged = () => {}) => render(<MemoryRouter><DataProvider><BlockView block={b} onChanged={onChanged} /></DataProvider></MemoryRouter>);
const saves = () => calls.filter(c => c.url.endsWith('/state'));

describe('requirements form', () => {
  it('shows conditional questions locally and autosaves once after the user stops editing, with no model call', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    view(mk('form', formSpec, { answers: { kind: 'business' } }));
    expect(screen.queryByLabelText(/payment provider/i)).toBeNull();
    fireEvent.click(screen.getByRole('radio', { name: 'E-commerce' }));
    expect(screen.getByLabelText(/payment provider/i)).toBeTruthy();                 // appears instantly, no network
    fireEvent.change(screen.getByLabelText(/payment provider/i), { target: { value: 'paypal' } });
    expect(saves()).toHaveLength(0);                                                  // debounced
    await act(async () => { await vi.advanceTimersByTimeAsync(900); });
    expect(saves()).toHaveLength(1);
    expect(saves()[0].body).toEqual({ version: 1, state: { answers: { kind: 'ecommerce', payments: 'paypal', accounts: false } } });
    expect(calls.some(c => /conversations|messages|send/.test(c.url))).toBe(false);
  });
  it('drops hidden answers and submits the saved version', async () => {
    const changed = vi.fn(); view(mk('form', formSpec, { answers: { kind: 'ecommerce', payments: 'paypal' } }), changed);
    fireEvent.click(screen.getByRole('radio', { name: 'Business' }));
    expect(screen.queryByLabelText(/payment provider/i)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /create the plan/i }));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    expect(saves().at(-1)!.body.state.answers).toEqual({ kind: 'business', accounts: false });
    const submit = calls.find(c => c.url.endsWith('/submit'))!; expect(submit.body).toEqual({ version: 2 });
  });
  it('is read-only once submitted and falls back safely for unknown specs', () => {
    view(mk('form', formSpec, { answers: {} }, { status: 'submitted' }));
    expect(screen.getByText(/being prepared/i)).toBeTruthy(); expect((screen.getByRole('radio', { name: 'Business' }) as HTMLButtonElement).disabled).toBe(true);
    cleanup(); view(mk('form', { ...formSpec, fields: [{ id: 'x', type: 'script', label: 'x' }] }, {}));
    expect(screen.getByText(/can’t be shown/i)).toBeTruthy();
  });
});

describe('running plan', () => {
  const gated = { ...planSpec, phases: [ph('analyze'), ph('build', ['analyze'], { requiresApproval: true, description: 'Spend the budget' }), ph('test', ['build'])] };
  const running = (run: any, status: any = 'awaiting_approval') => mk('task_plan', gated, { plan: gated, revision: 2 }, { status: 'launched', run_status: status, run, launched_request_id: 'r' });
  it('shows per-phase states, locks finished phases, and lets future phases be edited via the live endpoint', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    view(running({ analyze: done('analysis result'), build: { ...pend(), state: 'awaiting_approval' }, test: pend() }));
    expect(screen.getByText('Needs your approval')).toBeTruthy(); expect(screen.getByText('1 of 3 phases done')).toBeTruthy();
    expect(screen.getByText('analysis result')).toBeTruthy();                                         // finished phase shows its real result
    expect(screen.queryByRole('switch', { name: /Analyze enabled/ })).toBeNull();                     // locked
    expect(screen.getByRole('switch', { name: /Test enabled/ })).toBeTruthy();                        // not started: still editable
    fireEvent.click(screen.getByRole('switch', { name: /Test enabled/ }));
    await act(async () => { await vi.advanceTimersByTimeAsync(900); });
    const live = calls.find(c => c.url.endsWith('/live'))!; expect(live.body.version).toBe(1); expect(live.body.plan.phases.find((p: any) => p.id === 'test').enabled).toBe(false);
  });
  it('approves a gated phase and can skip or retry, each as a registered action', async () => {
    view(running({ analyze: done(), build: { ...pend(), state: 'awaiting_approval' }, test: pend() }));
    expect(screen.getByRole('group', { name: /Approval needed: Build/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Approve and run' }));
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/phase'))).toBe(true));
    expect(calls.find(c => c.url.endsWith('/phase'))!.body).toEqual({ phase_id: 'build', action: 'approve' });
    cleanup(); calls.length = 0;
    view(running({ analyze: done(), build: { ...pend(), state: 'failed', summary: 'The site build crashed' }, test: pend() }, 'failed'));
    expect(screen.getByText('The site build crashed')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(calls.find(c => c.url.endsWith('/phase'))!.body.action).toBe('retry'));
  });
  it('stops a running plan only after confirmation', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    view(running({ analyze: { ...done(), state: 'running' as const }, build: pend(), test: pend() }, 'running'));
    fireEvent.click(screen.getByRole('button', { name: 'Stop plan' }));
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/stop'))).toBe(true)); expect(confirm).toHaveBeenCalled();
  });
});

describe('plan diagram', () => {
  const open = async (name: string) => { fireEvent.click(screen.getByRole('button', { name: new RegExp(name) })); };
  it('renders phases in dependency rows and validates edits live', () => {
    view(mk('task_plan', planSpec, { plan: planSpec, revision: 1 }));
    expect(screen.getByRole('button', { name: /Launch plan \(3 phases\)/ }).hasAttribute('disabled')).toBe(false);
    fireEvent.click(screen.getByRole('switch', { name: /Build enabled/ }));            // switch off a prerequisite
    expect(screen.getByText(/“Test” needs|"Test" needs/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Launch plan/ }).hasAttribute('disabled')).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(screen.queryByText(/needs/)).toBeNull(); expect(screen.getByRole('button', { name: /Launch plan/ }).hasAttribute('disabled')).toBe(false);
  });
  it('renames, adds, and removes with a dependency warning, saving each change', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    view(mk('task_plan', planSpec, { plan: planSpec, revision: 1 }));
    await open('Analyze'); fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Understand needs' } });
    expect(screen.getByRole('button', { name: /Understand needs/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Add after' }));
    fireEvent.change(screen.getByLabelText('New phase name'), { target: { value: 'Security review' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(screen.getByRole('button', { name: /Security review/ })).toBeTruthy();
    await open('Understand needs'); await open('Build');
    fireEvent.click(screen.getByRole('button', { name: 'Remove' }));
    const dlg = screen.getByRole('alertdialog'); expect(within(dlg).getByText(/depends? on this phase/)).toBeTruthy();
    fireEvent.click(within(dlg).getByRole('button', { name: /reconnect/i }));
    expect(screen.queryByRole('button', { name: /^2 Build|Build$/ })).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(900); });
    const last = saves().at(-1)!.body.state.plan;
    expect(last.phases.map((p: any) => p.title)).toEqual(['Understand needs', 'Security review', 'Test']);
    expect(last.phases.find((p: any) => p.id === 'test').dependsOn).toEqual(['analyze']);
  });
  it('launches the saved version and becomes read-only with real run status', async () => {
    const changed = vi.fn(); view(mk('task_plan', planSpec, { plan: planSpec, revision: 1 }), changed);
    fireEvent.click(screen.getByRole('button', { name: /Launch plan/ }));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    expect(calls.find(c => c.url.endsWith('/launch'))!.body).toEqual({ version: 1 });
    cleanup(); view(mk('task_plan', planSpec, { plan: planSpec, revision: 2 }, { status: 'launched', launched_request_id: 'r1', run_status: 'completed',
      run: { analyze: done(), build: done(), test: done() } }));
    expect(screen.getAllByText('Done').length).toBeGreaterThan(3); expect(screen.queryByRole('button', { name: /Launch plan/ })).toBeNull(); expect(screen.queryByRole('switch')).toBeNull();
  });
  it('prevents circular dependencies in the editor and offers move controls without drag', async () => {
    view(mk('task_plan', planSpec, { plan: planSpec, revision: 1 }));
    await open('Analyze');
    const loop = screen.getByLabelText(/Test/, { selector: 'input[type=checkbox]' }) as HTMLInputElement;
    expect(loop.disabled).toBe(true);                                                   // test is downstream of analyze
    fireEvent.click(screen.getByRole('button', { name: 'Move down' }));
    const titles = screen.getAllByRole('button', { expanded: false }).map(b => b.textContent).join('|');
    expect(titles).toMatch(/Build/);
  });
});
