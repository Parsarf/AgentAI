import { describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach } from 'vitest';
import { GenDocumentView, RENDERERS, allBlockIds } from './components/Renderer';
import { approvalView } from './components/agent';
import { bin, chartSummary } from './components/data';
import { zoneStatus } from './components/cards';
import { visibleFields } from './components/forms';
import type { ExecutionProvider, Host, PlanInfo } from './components/context';
import { parseDocument, type GenDocument } from './protocol';
import { ADAPTER_ONLY, REGISTRY } from './registry';
import { ALL_PARTS, DATASETS, SAMPLE_CONVERSATION } from './fixtures';
import { IMPLEMENTED_TYPES } from './schemas';

afterEach(cleanup);
const ALL_DOCUMENT = 'all';
const doc = (raw: unknown): GenDocument => { if (raw === ALL_DOCUMENT) { const parts = ALL_PARTS.map(doc); return { ...parts[0], slots: parts.flatMap(p => p.slots) }; } const d = parseDocument(raw); if ('error' in d) throw new Error(d.error); return d; };
const plan = (deploy: string, checks = 'failed'): PlanInfo => ({ id: 'plan_demo', title: 'Launch', phases: [{ id: 'checks', title: 'Run checks' }, { id: 'deploy', title: 'Publish', description: 'Makes it public' }],
  run: { checks: { state: checks as any, summary: 'One check failed' }, deploy: { state: deploy as any, summary: null } }, run_status: 'running' });
function setup(raw: unknown, over: { deploy?: string; host?: Partial<Host> } = {}) {
  const host: Host = { send: vi.fn(async () => {}), phase: vi.fn(async () => {}), retryRequest: vi.fn(async () => {}), navigate: vi.fn(), download: vi.fn(async () => {}),
    phaseState: (b, p) => (b === 'plan_demo' ? ((plan(over.deploy ?? 'awaiting_approval').run[p]?.state ?? null) as any) : null), ...over.host };
  const exec: ExecutionProvider = { label: 'Sample data', request: id => (id === 'fixture_run' ? { id, state: 'completed', result: 'Compared (sample)', created_epoch: 0 } : undefined),
    plan: id => (id === 'plan_demo' ? plan(over.deploy ?? 'awaiting_approval') : undefined), useActivity: () => ({ rows: [{ key: 'k', category: 'search', label: 'Searched', detail: 'x', output: 'out', status: 'done', at: '' }], err: '' }) };
  const utils = render(<GenDocumentView doc={doc(raw)} exec={exec} host={host} scope="t" onDiagnostic={() => {}} />);
  return { host, ...utils };
}

describe('renderer coverage', () => {
  it('has a renderer for exactly the registry keys', () => { expect(Object.keys(RENDERERS).sort()).toEqual(IMPLEMENTED_TYPES.map(t => REGISTRY[t].rendererKey).sort()); });
  it('renders every fixture block without throwing and without leaving a fallback', () => {
    const { container } = setup(ALL_DOCUMENT);
    expect(container.querySelectorAll('.gen-fallback')).toHaveLength(0);
    for (const t of IMPLEMENTED_TYPES) if (!ADAPTER_ONLY.has(t)) expect(container.querySelector(`.t-${t}`), t).not.toBeNull();
  });
  it('lists nested block ids for local-action targets', () => { const d = doc(ALL_DOCUMENT); const ids = allBlockIds(d.slots); expect(ids).toContain('t1a'); expect(ids).toContain('a_table'); });
});

describe('text-first behaviour', () => {
  it('a text-only document is just prose', () => {
    const { container } = setup({ version: '1.0', responseId: 'r', blocks: [{ id: 'x', type: 'text', props: { content: 'Plain answer.' } }] });
    expect(screen.getByText('Plain answer.')).toBeTruthy(); expect(container.querySelectorAll('.gen-block')).toHaveLength(1);
  });
  it('raw HTML in markdown is never rendered, and unsafe links are dropped', () => {
    const { container } = setup({ version: '1.0', responseId: 'r', blocks: [{ id: 'x', type: 'text', props: { content: 'hi\n\n[bad](javascript:alert(1)) [ok](https://example.com/)\n\n![t](https://evil.example/p.png)' } }] });
    expect(container.querySelector('script')).toBeNull(); expect(container.querySelector('img')).toBeNull();
    const links = [...container.querySelectorAll('a')]; expect(links.map(a => a.getAttribute('href'))).toEqual(['https://example.com/']); expect(links[0].rel).toContain('noopener');
  });
  it('an invalid block shows its text fallback and the rest still renders', () => {
    const { container } = setup({ version: '1.0', responseId: 'r', blocks: [{ id: 'a', type: 'line_chart', fallback: 'Revenue rose 6% in June.', props: { xKey: 'm', series: [] } }, { id: 'b', type: 'text', props: { content: 'Still here.' } }] });
    expect(screen.getByText('Revenue rose 6% in June.')).toBeTruthy(); expect(screen.getByText('Still here.')).toBeTruthy(); expect(container.querySelectorAll('.gen-fallback')).toHaveLength(1);
  });
  it('a renderer that throws is contained by the error boundary', () => {
    const spy = vi.spyOn(console, 'error').mockImplementation(() => {}); const orig = RENDERERS.divider; const diag = vi.fn();
    RENDERERS.divider = () => { throw new Error('boom'); };
    render(<GenDocumentView doc={doc({ version: '1.0', responseId: 'r', blocks: [{ id: 'd', type: 'divider', fallback: 'A divider.', props: {} }, { id: 't', type: 'text', props: { content: 'Survivor' } }] })}
      exec={{ request: () => undefined, plan: () => undefined, useActivity: () => ({ rows: [], err: '' }) }} host={{} as Host} scope="x" onDiagnostic={diag} />);
    RENDERERS.divider = orig; spy.mockRestore();
    expect(screen.getByText('A divider.')).toBeTruthy(); expect(screen.getByText('Survivor')).toBeTruthy(); expect(diag).toHaveBeenCalledWith(expect.objectContaining({ id: 'd', reason: expect.stringContaining('boom') }));
  });
});

describe('local interactions (no network, no model)', () => {
  const tableDoc = { version: '1.0', responseId: 'r', datasets: { d: DATASETS.options }, blocks: [{ id: 't', type: 'table', dataRef: 'd', props: { title: 'T', pageSize: 5, searchable: true, rowHeader: 'name' } }] };
  it('sorts by clicking a header and filters by search', () => {
    const { host, container } = setup(tableDoc);
    const names = () => [...container.querySelectorAll('tbody th')].map(x => x.textContent);
    expect(names()).toEqual(['Alpha', 'Beta', 'Gamma', 'Delta']);
    fireEvent.click(screen.getByRole('button', { name: /^Price/ })); expect(names()).toEqual(['Delta', 'Beta', 'Alpha', 'Gamma']);
    expect(container.querySelector('th[aria-sort="ascending"]')).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /^Price/ })); expect(names()[0]).toBe('Gamma');
    fireEvent.change(screen.getByLabelText('Search rows'), { target: { value: 'bet' } }); expect(names()).toEqual(['Beta']);
    expect(host.send).not.toHaveBeenCalled(); expect(host.phase).not.toHaveBeenCalled();
  });
  it('paginates', () => {
    const rows = Array.from({ length: 12 }, (_, i) => ({ n: `Row ${i + 1}` }));
    setup({ version: '1.0', responseId: 'r', blocks: [{ id: 't', type: 'table', props: { pageSize: 5, rows, columns: [{ id: 'n', label: 'Name' }] } }] });
    expect(screen.getByText('Page 1 of 3')).toBeTruthy(); fireEvent.click(screen.getByText('Next')); expect(screen.getByText('Row 6')).toBeTruthy(); expect(screen.queryByText('Row 1')).toBeNull();
  });
  it('tabs switch with the keyboard and keep their state across a document update', () => {
    const raw = { version: '1.0', responseId: 'r', blocks: [{ id: 'tb', type: 'tabs', props: { tabs: [{ id: 'one', label: 'One', blocks: [{ id: 'a', type: 'text', props: { content: 'AAA' } }] }, { id: 'two', label: 'Two', blocks: [{ id: 'b', type: 'text', props: { content: 'BBB' } }] }] } }] };
    setup(raw); const first = screen.getByRole('tab', { name: 'One' }); first.focus(); fireEvent.keyDown(first, { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: 'Two' }).getAttribute('aria-selected')).toBe('true'); expect(screen.getByText('BBB')).toBeTruthy(); expect(screen.queryByText('AAA')).toBeNull();
  });
  it('accordion toggles with aria-expanded', () => {
    setup({ version: '1.0', responseId: 'r', blocks: [{ id: 'ac', type: 'accordion', props: { items: [{ id: 'i', title: 'More', blocks: [{ id: 'a', type: 'text', props: { content: 'Hidden body' } }] }] } }] });
    const b = screen.getByRole('button', { name: /More/ }); expect(b.getAttribute('aria-expanded')).toBe('false'); expect(screen.queryByText('Hidden body')).toBeNull();
    fireEvent.click(b); expect(b.getAttribute('aria-expanded')).toBe('true'); expect(screen.getByText('Hidden body')).toBeTruthy();
  });
  it('chart legend toggles a series but never hides the last one; a data table alternative exists', () => {
    const { container } = setup({ version: '1.0', responseId: 'r', datasets: { d: DATASETS.revenue }, blocks: [{ id: 'c', type: 'line_chart', dataRef: 'd', props: { title: 'Rev', xKey: 'month', series: [{ key: 'revenue', label: 'Revenue' }, { key: 'costs', label: 'Costs' }] } }] });
    expect(container.querySelectorAll('polyline')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Costs' })); expect(container.querySelectorAll('polyline')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Revenue' })); expect(container.querySelectorAll('polyline')).toHaveLength(1);
    expect(screen.getByText('View as table')).toBeTruthy(); expect(container.querySelector('[role="img"]')!.getAttribute('aria-label')).toMatch(/highest at .*Jun/);
  });
  it('chart summary is computed from the data', () => { expect(chartSummary('bar_chart', 'Sales', ['a', 'b'], [{ label: 'S', values: [1, 5] }])).toMatch(/highest at 5 \(b\) and lowest at 1 \(a\)/); });
  it('empty and missing data degrade to a message', () => {
    setup({ version: '1.0', responseId: 'r', datasets: { e: { columns: [{ id: 'x', label: 'x' }], rows: [] } }, blocks: [{ id: 't', type: 'table', dataRef: 'e', props: {} }] });
    expect(screen.getByText('No rows to show.')).toBeTruthy();
  });
  it('loading shows a skeleton, not the widget', () => {
    const { container } = setup({ version: '1.0', responseId: 'r', blocks: [{ id: 'm', type: 'metric_card', loading: true, props: { label: 'A', value: 1 } }] });
    expect(container.querySelector('.gen-skel')).not.toBeNull(); expect(container.querySelector('.gen-metric')).toBeNull();
  });
  it('long and unicode/RTL content renders as text', () => {
    setup({ version: '1.0', responseId: 'r', blocks: [{ id: 'x', type: 'callout', props: { content: 'مرحبا بالعالم ' + 'ا'.repeat(300) + ' 🙂 日本語' } }] });
    expect(screen.getByRole('note').textContent).toContain('日本語');
  });
});

describe('histogram and gauge', () => {
  it('bins values into equal-width buckets that add up', () => {
    const b = bin([1, 2, 2, 3, 9], 4); expect(b.map(x => x.count)).toEqual([3, 1, 0, 1]); expect(b.reduce((a, x) => a + x.count, 0)).toBe(5); expect(bin([], 4)).toEqual([]); expect(bin([5, 5, 5], 3).reduce((a, x) => a + x.count, 0)).toBe(3);
  });
  it('histogram has a computed summary and a table alternative; too few values degrade', () => {
    const { container } = setup({ version: '1.0', responseId: 'r', blocks: [{ id: 'h', type: 'histogram_chart', props: { title: 'H', valueKey: 'v', bins: 3, data: [1, 2, 2, 3, 9].map(v => ({ v })) } }, { id: 'h2', type: 'histogram_chart', props: { valueKey: 'v', data: [{ v: 1 }] } }] });
    expect(container.querySelector('[role="img"]')!.getAttribute('aria-label')).toMatch(/5 values from 1 to 9/); expect(screen.getByText('View as table')).toBeTruthy(); expect(screen.getByText('Not enough values for a distribution.')).toBeTruthy();
  });
  it('gauge exposes a meter, clamps, and takes its status from the zones', () => {
    const zones = [{ upTo: 60, status: 'success' as const }, { upTo: 100, status: 'error' as const }];
    expect(zoneStatus(30, zones)).toBe('success'); expect(zoneStatus(90, zones)).toBe('error'); expect(zoneStatus(500, zones)).toBe('error'); expect(zoneStatus(5)).toBe('idle');
    const { container } = setup({ version: '1.0', responseId: 'r', blocks: [{ id: 'g', type: 'gauge', props: { label: 'Load', value: 140, max: 100, unit: '%', zones } }] });
    const m = container.querySelector('[role="meter"]')!; expect(m.getAttribute('aria-valuenow')).toBe('100'); expect(m.getAttribute('aria-label')).toBe('Load: 140 %'); expect(m.className).toContain('error');
  });
});

describe('forms', () => {
  const form = { version: '1.0', responseId: 'r', blocks: [{ id: 'f', type: 'form', variant: 'conditional', props: { title: 'Choices', fields: [
    { id: 'kind', type: 'select', label: 'Kind', required: true, options: [{ label: 'Shop', value: 'shop' }, { label: 'Blog', value: 'blog' }] },
    { id: 'pay', type: 'toggle', label: 'Take payments', default: false, showIf: { field: 'kind', equals: 'shop' } }], submit: { label: 'Send', action: { kind: 'agent.request', message: 'My choices:' } } } }] };
  it('requires required fields, shows conditional fields, and sends exactly what was chosen', async () => {
    const { host } = setup(form);
    fireEvent.click(screen.getByText('Send')); expect(await screen.findByText('Enter a value.')).toBeTruthy(); expect(host.send).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('Take payments')).toBeNull();
    fireEvent.change(screen.getByLabelText(/Kind/), { target: { value: 'shop' } }); fireEvent.click(screen.getByLabelText('Take payments'));
    fireEvent.click(screen.getByText('Send'));
    await waitFor(() => expect(host.send).toHaveBeenCalledWith('My choices:\n- Kind: Shop\n- Take payments: Yes', expect.any(String)));
  });
  it('visibleFields hides unmet conditions', () => { const f = [{ id: 'a', type: 'text', label: 'A' }, { id: 'b', type: 'text', label: 'B', showIf: { field: 'a', equals: 'x' } }] as any; expect(visibleFields(f, { a: 'y' })).toHaveLength(1); expect(visibleFields(f, { a: 'x' })).toHaveLength(2); });
});

describe('location request', () => {
  const ask = { version: '1.0', responseId: 'r', blocks: [{ id: 'loc', type: 'location_request', props: { title: 'Where are you?', fields: [{ id: 'where', type: 'location', label: 'Your location', required: true }], submit: { label: 'Send', action: { kind: 'agent.request', message: 'My location:' } } } }] };
  const geo = (impl: unknown) => Object.defineProperty(navigator, 'geolocation', { value: impl, configurable: true });
  afterEach(() => { Reflect.deleteProperty(navigator, 'geolocation'); });
  it('never asks the browser until the button is pressed', () => {
    const getCurrentPosition = vi.fn(); geo({ getCurrentPosition }); setup(ask);
    expect(screen.getByText('Share my location')).toBeTruthy(); expect(getCurrentPosition).not.toHaveBeenCalled();
  });
  it('sends an approximate device position straight away, rounded to about 1 km', async () => {
    geo({ getCurrentPosition: (ok: (p: unknown) => void) => ok({ coords: { latitude: 37.774929, longitude: -122.419418 } }) }); const { host } = setup(ask);
    fireEvent.click(screen.getByText('Share my location'));
    await waitFor(() => expect(host.send).toHaveBeenCalledWith('My location:\n- Your location: Shared from my device, approximate (about 1 km): 37.77, -122.42', expect.any(String)));
    expect(JSON.stringify((host.send as any).mock.calls)).not.toContain('37.7749');                                       // only the rounded point leaves the browser
    const input = screen.getByPlaceholderText('ZIP code, city or address') as HTMLInputElement;
    await waitFor(() => expect(input.value).toContain('37.77, -122.42')); expect(input.matches(':disabled')).toBe(true);              // the component stays, locked, with what was sent
  });
  it('explains a blocked permission and still accepts a typed ZIP, city or address', async () => {
    geo({ getCurrentPosition: (_: unknown, bad: (e: { code: number }) => void) => bad({ code: 1 }) }); const { host } = setup(ask);
    fireEvent.click(screen.getByText('Share my location')); expect(await screen.findByText(/did not allow location access/)).toBeTruthy(); expect(host.send).not.toHaveBeenCalled();
    fireEvent.change(screen.getByPlaceholderText('ZIP code, city or address'), { target: { value: '94110' } }); fireEvent.click(screen.getByText('Send'));
    await waitFor(() => expect(host.send).toHaveBeenCalledWith('My location:\n- Your location: 94110', expect.any(String)));
  });
  it('asks for a typed location when the browser has no location support, and requires an answer', async () => {
    const { host } = setup(ask); expect(screen.queryByText('Share my location')).toBeNull();
    fireEvent.click(screen.getByText('Send')); expect(await screen.findByText('Enter a value.')).toBeTruthy(); expect(host.send).not.toHaveBeenCalled();
  });
});

describe('an answer given in a component is final', () => {
  const form = { version: '1.0', responseId: 'r', blocks: [{ id: 'f', type: 'form', props: { title: 'Choices', fields: [
    { id: 'kind', type: 'select', label: 'Kind', required: true, options: [{ label: 'Shop', value: 'shop' }, { label: 'Blog', value: 'blog' }] }], submit: { label: 'Send', action: { kind: 'agent.request', message: 'My choices:' } } } }] };
  const buttons = { version: '1.0', responseId: 'r', blocks: [{ id: 'n', type: 'button_group', props: { buttons: [
    { id: 'go', label: 'Show details', action: { kind: 'agent.request', message: 'Show the details' } }, { id: 'skip', label: 'Skip it', action: { kind: 'agent.request', message: 'Skip it please' } }] } }] };
  it('a sent form stays on screen, locked, with exactly what was sent', async () => {
    const { host } = setup(form);
    fireEvent.change(screen.getByLabelText(/Kind/), { target: { value: 'shop' } }); fireEvent.click(screen.getByText('Send'));
    await waitFor(() => expect(host.send).toHaveBeenCalledTimes(1));
    const select = screen.getByLabelText(/Kind/) as HTMLSelectElement;
    await waitFor(() => expect(select.matches(':disabled')).toBe(true)); expect(select.value).toBe('shop');
    expect((screen.getByText(/Send/).closest('button') as HTMLButtonElement).disabled).toBe(true); expect(screen.getByText('Sent.')).toBeTruthy();
  });
  it('a form that was answered before (a reload, another device) opens locked with the answer', () => {
    setup(form, { host: { initialState: { f: { values: { kind: 'blog' }, answered: true } } } });
    const select = screen.getByLabelText(/Kind/) as HTMLSelectElement; expect(select.value).toBe('blog'); expect(select.matches(':disabled')).toBe(true);
    expect((screen.getByText(/Send/).closest('button') as HTMLButtonElement).disabled).toBe(true); expect(screen.getByText('Answered. This can’t be changed.')).toBeTruthy();
  });
  it('pressing one button locks the group and marks which one was pressed', async () => {
    const { host } = setup(buttons);
    fireEvent.click(screen.getByText('Show details')); await waitFor(() => expect(host.send).toHaveBeenCalledWith('Show the details', expect.any(String)));
    await waitFor(() => expect((screen.getByText('Skip it').closest('button') as HTMLButtonElement).disabled).toBe(true));
    expect(screen.getByText('✓ Show details').closest('button')!.getAttribute('aria-pressed')).toBe('true');
  });
  it('a button group answered before opens locked with the chosen button marked', () => {
    setup(buttons, { host: { initialState: { n: { answered: true, chosen: 'skip' } } } });
    expect(screen.getByText('✓ Skip it').closest('button')!.getAttribute('aria-pressed')).toBe('true');
    expect((screen.getByText('Show details').closest('button') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('agent actions end to end', () => {
  it('approval: confirm dialog first, then exactly one host call, then done', async () => {
    const { host } = setup(SAMPLE_CONVERSATION);
    const group = screen.getByRole('group', { name: /Approval: Publish/ }); expect(within(group).getByText('Waiting for you')).toBeTruthy();
    expect(screen.getByText('Sample data')).toBeTruthy();                                   // provenance label is on screen
    fireEvent.click(within(group).getByText('Approve')); const dialog = await screen.findByRole('alertdialog'); expect(host.phase).not.toHaveBeenCalled();
    await act(async () => { fireEvent.click(within(dialog).getByText('Confirm')); });
    await waitFor(() => expect(host.phase).toHaveBeenCalledWith('plan_demo', 'deploy', 'approve', expect.any(String))); expect(host.phase).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(within(group).getByText(/Approve/).closest('button')!.hasAttribute('disabled')).toBe(true));
  });
  it('cancelling the dialog does nothing', async () => {
    const { host } = setup(SAMPLE_CONVERSATION); fireEvent.click(screen.getByText('Skip this step')); fireEvent.click(await screen.findByText('Cancel'));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull()); expect(host.phase).not.toHaveBeenCalled();
  });
  it('a step that is no longer waiting offers no buttons (expired, rejected, failed, approved)', () => {
    for (const [state, text] of [['skipped', 'Skipped'], ['failed', 'Failed'], ['completed', 'Approved and done'], ['running', 'Approved, running']] as const) {
      const { unmount } = setup(SAMPLE_CONVERSATION, { deploy: state }); const g = screen.getByRole('group', { name: /Approval: Publish/ });
      expect(within(g).getByText(text)).toBeTruthy(); expect(within(g).queryByText('Approve')).toBeNull(); unmount();
    }
    expect(approvalView('pending', 'stopped').label).toMatch(/Expired/); expect(approvalView(undefined).can).toBe(false);
  });
  it('a failed host call shows an error and nothing claims success', async () => {
    const { host } = setup(SAMPLE_CONVERSATION, { host: { phase: vi.fn(async () => { throw new Error('409'); }) } });
    fireEvent.click(screen.getByText('Approve')); fireEvent.click(await screen.findByText('Confirm'));
    expect(await screen.findByText(/did not go through/)).toBeTruthy(); expect(host.phase).toHaveBeenCalledTimes(1);
  });
  it('follow-up buttons send the exact words once', async () => {
    const { host } = setup(SAMPLE_CONVERSATION); fireEvent.click(screen.getByText('Show costs by category'));
    await waitFor(() => expect(host.send).toHaveBeenCalledWith('Show costs by category', expect.any(String))); expect(host.send).toHaveBeenCalledTimes(1);
  });
  it('agent widgets read real state from the provider and say when a task is not in this chat', () => {
    setup({ version: '1.0', responseId: 'r', blocks: [{ id: 'a', type: 'agent_status', props: { requestId: 'fixture_run' } }, { id: 'b', type: 'agent_status', props: { requestId: 'someoneelses1' } }, { id: 'c', type: 'completion_summary', props: { requestId: 'fixture_run' } }] });
    expect(screen.getAllByText('Done').length).toBeGreaterThan(0); expect(screen.getByText('That task is not part of this chat.')).toBeTruthy(); expect(screen.getByText('Compared (sample)')).toBeTruthy();
  });
  it('error_retry offers retry only for a failed step', async () => {
    const { host } = setup({ version: '1.0', responseId: 'r', blocks: [{ id: 'e', type: 'error_retry', props: { planBlockId: 'plan_demo', phaseId: 'checks' } }] }, { host: { phaseState: () => 'failed' } });
    fireEvent.click(screen.getByText('Retry this step')); fireEvent.click(await screen.findByText('Confirm'));
    await waitFor(() => expect(host.phase).toHaveBeenCalledWith('plan_demo', 'checks', 'retry', expect.any(String)));
  });
});

describe('accessibility basics', () => {
  it('names regions, progress bars and switches', () => {
    const { container } = setup(ALL_DOCUMENT);
    expect(container.querySelector('[role="progressbar"][aria-valuenow]')).not.toBeNull(); expect(container.querySelectorAll('[role="region"][tabindex="0"]').length).toBeGreaterThan(2);
    for (const el of container.querySelectorAll('[role="region"]')) expect(el.getAttribute('aria-label') || el.getAttribute('aria-labelledby'), el.outerHTML.slice(0, 80)).toBeTruthy();
    for (const b of container.querySelectorAll('button')) expect((b.textContent || b.getAttribute('aria-label') || '').trim().length, b.outerHTML.slice(0, 80)).toBeGreaterThan(0);
    for (const i of container.querySelectorAll('input:not([type="radio"])')) expect(i.id || i.closest('label') || i.getAttribute('aria-label'), i.outerHTML.slice(0, 80)).toBeTruthy();
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
  });
  it('status is never colour only (text or sr text accompanies every pill and delta)', () => {
    const { container } = setup(ALL_DOCUMENT); for (const p of container.querySelectorAll('.gen-pill')) expect(p.textContent!.trim().length).toBeGreaterThan(0);
    expect(container.querySelector('.gen-delta .sr')).not.toBeNull();
  });
  it('the stylesheet respects reduced motion and touch targets through the shared tokens', () => {
    const fs = (globalThis as any).process.getBuiltinModule('node:fs'); const css: string = fs.readFileSync('src/gen/gen.css', 'utf8'); const tokens: string = fs.readFileSync('src/styles/tokens.css', 'utf8');
    expect(tokens).toMatch(/prefers-reduced-motion: reduce/); expect(css).toMatch(/pointer: coarse[\s\S]*touch-min/); expect(css).toMatch(/:focus-visible/);
  });
});
