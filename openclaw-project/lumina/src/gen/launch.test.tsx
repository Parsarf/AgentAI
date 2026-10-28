import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ApiError } from '../lib/api';
import { ArtifactDraft, artifactDraft, bindDraftAccount, clearArtifactDrafts, pauseArtifactDrafts } from './drafts';
import { fieldError } from './formValidation';
import { interactionError } from './errors';
import { GenDocumentView } from './components/Renderer';
import { parseDocument } from './protocol';
import type { Host, ExecutionProvider } from './components/context';
afterEach(() => { cleanup(); clearArtifactDrafts(); });
const base = { form: { values: { quantity: 1, name: 'old' } } };
it('serializes overlapping saves and flushes the newest edit', async () => {
  const d = new ArtifactDraft(1, base); let finish!: () => void;
  const save = vi.fn().mockImplementationOnce(() => new Promise<void>(r => { finish = r; })).mockResolvedValue(undefined); d.host = { saveState: save };
  d.patch('form', { values: { quantity: 2, name: 'old' } });
  const pending = d.flush(); await Promise.resolve();
  d.patch('form', { values: { quantity: 3, name: 'old' } }); expect(d.flush()).toBe(pending);
  finish(); await pending;
  expect(save.mock.calls.map(c => c[0].form.values.quantity)).toEqual([2, 3]); expect(d.getSnapshot().dirty).toBe(false);
});
it('retains offline edits and retries without losing answers', async () => {
  const d = artifactDraft('a', 1, base); d.patch('form', { values: { quantity: 4 } });
  const save = vi.fn().mockRejectedValueOnce(new TypeError('network')).mockResolvedValue(undefined); d.host = { saveState: save };
  await expect(d.flush()).rejects.toThrow(); expect(d.getSnapshot().dirty).toBe(true);
  const reopened = artifactDraft('a', 1, base); expect(reopened.getSnapshot().state.form.values).toEqual({ quantity: 4 });
  await reopened.flush(); expect(reopened.getSnapshot().dirty).toBe(false);
});
it('merges edits to separate fields after a revision conflict', async () => {
  const d = new ArtifactDraft(1, base); d.patch('form', { values: { quantity: 4, name: 'old' } });
  const save = vi.fn().mockRejectedValueOnce(new ApiError('version_conflict', 409)).mockResolvedValue(undefined);
  d.host = { saveState: save, loadState: async () => ({ version: 1, state: { form: { values: { quantity: 1, name: 'new' } } } }) };
  await d.flush(); expect(save.mock.calls[1][0].form.values).toEqual({ quantity: 4, name: 'new' });
});
it.each([true, false])('requires an explicit decision for overlapping edits (keep mine=%s)', async keep => {
  const d = new ArtifactDraft(1, base); d.patch('form', { values: { quantity: 4, name: 'old' } });
  const save = vi.fn().mockRejectedValueOnce(new ApiError('version_conflict', 409)).mockResolvedValue(undefined);
  d.host = { saveState: save, loadState: async () => ({ version: 1, state: { form: { values: { quantity: 7, name: 'new' } } } }) };
  await expect(d.flush()).rejects.toThrow(); expect(d.getSnapshot().conflict).toBe(true); expect(save).toHaveBeenCalledTimes(1);
  await d.resolve(keep); expect(d.getSnapshot().state.form.values).toEqual({ quantity: keep ? 4 : 7, name: 'new' }); expect(d.getSnapshot().dirty).toBe(false);
});
it('does not overwrite a newer artifact document', async () => {
  const d = new ArtifactDraft(1, base); d.patch('form', { values: { quantity: 4 } });
  const save = vi.fn().mockRejectedValue(new ApiError('version_conflict', 409)); d.host = { saveState: save, loadState: async () => ({ version: 2, state: {} }) };
  await expect(d.flush()).rejects.toThrow(); expect(save).toHaveBeenCalledTimes(1); expect(d.getSnapshot().state.form.values).toEqual({ quantity: 4 });
});
it('reopening against newer saved state cannot overwrite another tab silently', () => {
  const d = artifactDraft('a', 1, base); d.patch('form', { values: { quantity: 4 } });
  const same = artifactDraft('a', 1, { form: { values: { quantity: 7 } } }); expect(same.getSnapshot().conflict).toBe(true);
});
it('pauses expired sessions, restores same-account drafts and clears on account change', async () => {
  bindDraftAccount('a@example.test'); const d = artifactDraft('a', 1, base); const save = vi.fn(async () => {}); d.host = { saveState: save }; d.patch('form', { values: { quantity: 4 } });
  pauseArtifactDrafts(); await d.flush(); expect(save).not.toHaveBeenCalled();
  bindDraftAccount('a@example.test'); expect(artifactDraft('a', 1, base)).toBe(d);
  bindDraftAccount('b@example.test'); expect(artifactDraft('a', 1, base)).not.toBe(d);
});
it.each([
  ['number', 21, { min: 1, max: 20 }], ['number', 1.5, { step: 1 }], ['date', '2026-02-30', {}], ['time', '25:01', {}], ['range', [4, 1], {}], ['date-range', ['2026-02-01', '2026-01-01'], {}], ['color', 'red', {}],
])('rejects invalid %s values before submission', (type, value, props) => { expect(fieldError({ id: 'x', label: 'Value', type, ...props } as any, value)).toBeTruthy(); });
it('keeps optional empty fields valid and accepts leap days and false toggles', () => {
  expect(fieldError({ id: 'x', label: 'Date', type: 'date' }, '2028-02-29')).toBeUndefined();
  expect(fieldError({ id: 'x', label: 'Text', type: 'text' }, '')).toBeUndefined();
  expect(fieldError({ id: 'x', label: 'Toggle', type: 'toggle', required: true }, false)).toBeUndefined();
});
it.each([401, 402, 403, 404, 409, 429, 503])('explains HTTP %s without echoing backend content', status => {
  expect(interactionError(new ApiError('private exception', status))).not.toContain('private');
  expect(interactionError(new ApiError('private exception', status)).length).toBeGreaterThan(30);
});
const exec: ExecutionProvider = { request: () => undefined, plan: () => undefined, useActivity: () => ({ rows: [], err: '' }) };
const form = { version: '1.0', responseId: 'form', blocks: [{ id: 'choices', type: 'form', props: { fields: [{ id: 'quantity', label: 'Quantity', type: 'number', min: 1, max: 20, default: 2 }], submit: { label: 'Calculate', action: { kind: 'agent.request', message: 'Calculate total' } } } }] };
function show(overrides: Partial<Host> = {}) {
  const doc = parseDocument(form); if ('error' in doc) throw new Error(doc.error);
  const host: Host = { send: vi.fn(async () => {}), phase: vi.fn(async () => {}), retryRequest: vi.fn(async () => {}), download: vi.fn(async () => {}), navigate: vi.fn(), phaseState: () => null, ...overrides };
  return { host, ...render(<GenDocumentView doc={doc} host={host} exec={exec} scope="launch-form" />) };
}
it('associates range errors with the field, focuses it, and sends no request', async () => {
  const submit = vi.fn(async () => {}); show({ submit });
  const quantity = screen.getByLabelText('Quantity'); fireEvent.change(quantity, { target: { value: '40' } }); fireEvent.click(screen.getByText('Calculate'));
  await waitFor(() => expect(quantity.getAttribute('aria-invalid')).toBe('true'));
  await waitFor(() => expect(document.activeElement).toBe(quantity)); expect(submit).not.toHaveBeenCalled();
  expect(document.getElementById(quantity.getAttribute('aria-describedby')!)?.textContent).toContain('20');
});
it('retains event identity across a lost response and route remount', async () => {
  const submit = vi.fn().mockRejectedValueOnce(new TypeError('lost response')).mockResolvedValue(undefined);
  const first = show({ artifactVersion: 1, submit }); fireEvent.click(screen.getByText('Calculate'));
  await screen.findByText(/Could not connect/); first.unmount();
  show({ artifactVersion: 1, submit }); fireEvent.click(screen.getByText('Calculate'));
  await waitFor(() => expect(submit).toHaveBeenCalledTimes(2)); expect(submit.mock.calls[0][3]).toBe(submit.mock.calls[1][3]);
});
it('offers retry saving after failure without discarding input', async () => {
  const save = vi.fn().mockRejectedValueOnce(new TypeError('offline')).mockResolvedValue(undefined);
  show({ saveState: save }); fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '9' } });
  fireEvent.click(await screen.findByRole('button', { name: 'Retry saving' }));
  await screen.findByText('Changes saved'); expect((screen.getByLabelText('Quantity') as HTMLInputElement).value).toBe('9');
});
