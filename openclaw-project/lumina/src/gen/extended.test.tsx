import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { GenDocumentView } from './components/Renderer';
import { parseDocument } from './protocol';
import { calculate, haversine } from './operations';
import { FAMILIES, ALIASES } from './catalog';
import { ALL_BLOCKS } from './fixtures';
import type { ExecutionProvider, Host } from './components/context';
afterEach(cleanup);
const exec: ExecutionProvider = { request: () => undefined, plan: () => undefined, useActivity: () => ({ rows: [], err: '' }) };
function show(block: any, overrides: Partial<Host> = {}) {
  const d = parseDocument({ type: 'document', version: '1.0', responseId: 'test', blocks: [block] });
  if ('error' in d) throw new Error(d.error);
  const host: Host = { send: vi.fn(async () => {}), phase: vi.fn(async () => {}), retryRequest: vi.fn(async () => {}), navigate: vi.fn(), download: vi.fn(async () => {}), phaseState: () => null, ...overrides };
  return { host, ...render(<GenDocumentView doc={d} exec={exec} host={host} scope="artifact-test" />) };
}
const fixture = (type: string) => ALL_BLOCKS.find((b: any) => b.type === type) as any;
describe('catalog capability behavior', () => {
  it('has a fixture for every shared capability and family', () => {
    for (const type of [...Object.keys(FAMILIES), ...Object.keys(ALIASES)]) expect(fixture(type), type).toBeTruthy();
  });
  it('recalculates a what-if without an agent request', async () => {
    const { host } = show(fixture('scenario_simulator'));
    expect(await screen.findByText('Result: 300')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '4' } });
    expect(screen.getByText('Result: 400')).toBeTruthy();
    expect(host.send).not.toHaveBeenCalled();
  });
  it('reweights decision matrix scenarios locally', async () => {
    const { host } = show(fixture('decision_matrix'));
    expect(await screen.findByText('7.33')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Weight for Quality'), { target: { value: '0' } });
    expect(screen.getByText('6.00')).toBeTruthy();
    expect(screen.getByText('9.00')).toBeTruthy();
    expect(host.send).not.toHaveBeenCalled();
  });
  it('sends validated form fields through the artifact event host', async () => {
    const submit = vi.fn(async () => {});
    show({ id: 'form', type: 'form', props: { fields: [{ id: 'quantity', type: 'number', label: 'Quantity', min: 1, max: 10, required: true }], submit: { label: 'Calculate', action: { kind: 'agent.request', message: 'Calculate the total' } } } }, { submit });
    fireEvent.change(screen.getByLabelText(/Quantity/), { target: { value: '4' } });
    fireEvent.click(screen.getByRole('button', { name: 'Calculate' }));
    await waitFor(() => expect(submit).toHaveBeenCalledWith('form', 'submit', { quantity: 4 }, expect.any(String)));
    expect(screen.getByText('Sent.')).toBeTruthy();
  });
  it('flushes pending local state before a fast form submission', async () => {
    let finish!: () => void;
    const saveState = vi.fn(() => new Promise<void>(resolve => { finish = resolve; }));
    const submit = vi.fn(async () => {});
    show({ id: 'form', type: 'form', props: { fields: [{ id: 'quantity', type: 'number', label: 'Quantity', default: 1 }], submit: { label: 'Send values', action: { kind: 'agent.request', message: 'Calculate the total' } } } }, { saveState, submit });
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '4' } });
    fireEvent.click(screen.getByRole('button', { name: 'Send values' }));
    await waitFor(() => expect(saveState).toHaveBeenCalledTimes(1));
    expect(submit).not.toHaveBeenCalled();
    finish();
    await waitFor(() => expect(submit).toHaveBeenCalledWith('form', 'submit', { quantity: 4 }, expect.any(String)));
  });
  it('restores local inputs and saves edits against their stable node id', async () => {
    const saveState = vi.fn(async () => {});
    show(fixture('calculator'), { initialState: { fixture_calculator: { values: { price: 20, count: 2 } } }, saveState });
    expect(await screen.findByText('Result: 40')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '3' } });
    await waitFor(() => expect(saveState).toHaveBeenCalledWith(expect.objectContaining({ fixture_calculator: { values: { price: 20, count: 3 } } })));
  });
  it('uses keyboard-operable task checklists', async () => {
    show(fixture('checklist'));
    const item = await screen.findByRole('checkbox', { name: 'Review findings' });
    fireEvent.click(item); expect((item as HTMLInputElement).checked).toBe(true);
  });
  it('pages and edits data without writing to a database', async () => {
    show(fixture('editable_table'));
    const input = await screen.findByLabelText('Value, row 1');
    fireEvent.change(input, { target: { value: '15' } });
    expect((input as HTMLInputElement).value).toBe('15');
    expect(screen.getByText(/Edits are saved in this artifact/)).toBeTruthy();
  });
  it('moves Kanban items with an accessible select', async () => {
    show(fixture('kanban'));
    const selects = await screen.findAllByLabelText('Move to');
    fireEvent.change(selects[0], { target: { value: 'done' } });
    expect((screen.getAllByLabelText('Move to').find(e => (e as HTMLSelectElement).value === 'done') as HTMLSelectElement)).toBeTruthy();
  });
  it('builds and evaluates rules using the allowlisted operators', async () => {
    show(fixture('rule_builder'));
    expect(await screen.findByText('Matches the provided values')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Value'), { target: { value: '1000' } });
    expect(screen.getByText('Does not match the provided values')).toBeTruthy();
  });
  it('never loads remote images or gives media an unsandboxed document', async () => {
    const { container } = show(fixture('pdf_viewer'), { assetUrl: () => '/v1/genui/artifacts/artifact-test/asset?path=sample.pdf' });
    await waitFor(() => expect(container.querySelector('iframe')).not.toBeNull());
    expect(container.querySelector('iframe')?.getAttribute('sandbox')).toBe('');
  });
});
describe('controlled numeric operations', () => {
  it('handles arithmetic, weights, compounding and budget totals', () => {
    expect(calculate('multiply', [100, 4])).toBe(400);
    expect(calculate('weighted_average', [10, 20], [1, 3])).toBe(17.5);
    expect(calculate('compound', [100, 10, 2])).toBeCloseTo(121);
    expect(calculate('budget', [100, 200], [], 500)).toBe(200);
    expect(haversine({ lat: 0, lon: 0 }, { lat: 0, lon: 0 })).toBe(0);
  });
  it('rejects code, division by zero, nonfinite values and overflow', () => {
    for (const [op, values] of [['eval(x)', [1]], ['divide', [10, 0]], ['sum', [NaN]], ['compound', [1e15, 100, 1000]]] as Array<[string, number[]]>) expect(() => calculate(op, values)).toThrow();
  });
});
