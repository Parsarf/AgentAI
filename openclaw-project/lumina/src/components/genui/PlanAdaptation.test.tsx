import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import PlanAdaptation, { changeLines } from './PlanAdaptation';
import type { Block, PlanDiff, Proposal } from '../../lib/genui/schema';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const diff: PlanDiff = { added: [{ id: 'b2', title: 'Another way', description: '', enabled: true, optional: false, requiresApproval: false, dependsOn: ['a'] }], removed: [], changed: [{ id: 'c', title: 'Ship it', fields: ['dependsOn'] }], reordered: false, title_changed: false };
const proposal = (over: Partial<Proposal> = {}): Proposal => ({ id: 'p1', trigger: 'failure', instruction: '', state: 'proposed', summary: 'This revision adds "Another way".', auto: false, base_revision: 2, diff, plan: null, created_epoch: 1, decided_epoch: null, ...over });
const block = (over: Partial<Block> = {}): Block => ({ id: 'blk', conversation_id: 'c', anchor_message_id: null, kind: 'task_plan', schema_version: '1.0', spec: {}, state: {}, version: 3, status: 'launched', launched_request_id: null,
  run_status: 'failed', proposals: [], replan: { auto: false, auto_used: 0, auto_limit: 2 }, ...over });
const calls = () => { const seen: { url: string; body: any }[] = []; vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => { if (url === '/v1/csrf') return reply({ csrf_token: 't' }); seen.push({ url, body: init?.body ? JSON.parse(init.body as string) : undefined }); return reply({ ok: true }); })); return seen; };

describe('PlanAdaptation', () => {
  it('words a revision as a list of changes', () => {
    expect(changeLines(diff)).toEqual(['Adds “Another way”', 'Changes “Ship it” (what it runs after)']);
    expect(changeLines({ ...diff, added: [], changed: [], removed: ['old'], reordered: true, title_changed: true })).toEqual(['Removes the phase “old”', 'Changes the order of the phases', 'Renames the plan']);
  });

  it('shows a suggested revision with what it changes, and applies it only when asked', async () => {
    const seen = calls(); const changed = vi.fn();
    render(<PlanAdaptation block={block({ proposals: [proposal()] })} onChanged={changed} failed />);
    expect(screen.getByText('Adds “Another way”')).toBeTruthy(); expect(screen.getByText(/stay exactly as they are/)).toBeTruthy();
    expect(seen).toEqual([]);                                                          // nothing was sent by showing it
    fireEvent.click(screen.getByRole('button', { name: 'Apply this change' }));
    await waitFor(() => expect(changed).toHaveBeenCalled());
    expect(seen).toEqual([{ url: '/v1/blocks/blk/proposal', body: { proposal_id: 'p1', action: 'approve' } }]);
  });

  it('declines a revision', async () => {
    const seen = calls();
    render(<PlanAdaptation block={block({ proposals: [proposal()] })} onChanged={() => {}} failed />);
    fireEvent.click(screen.getByRole('button', { name: 'No thanks' }));
    await waitFor(() => expect(seen.length).toBe(1));
    expect(seen[0].body).toEqual({ proposal_id: 'p1', action: 'decline' });
  });

  it('has no buttons on a revision that will be applied by itself', () => {
    calls();
    render(<PlanAdaptation block={block({ proposals: [proposal({ auto: true })] })} onChanged={() => {}} failed={false} />);
    expect(screen.getByText(/applied by itself/)).toBeTruthy(); expect(screen.queryByRole('button', { name: 'Apply this change' })).toBeNull();
  });

  it('says the assistant is working, and does not allow a second ask meanwhile', () => {
    calls();
    render(<PlanAdaptation block={block({ proposals: [proposal({ state: 'requested', diff: null })] })} onChanged={() => {}} failed />);
    expect(screen.getByRole('status').textContent).toMatch(/working on a revision/);
    expect((screen.getByLabelText('Ask for a change to the plan') as HTMLInputElement).disabled).toBe(true);
  });

  it('asks for a change in the customer\'s words, and for a new plan after a failure', async () => {
    const seen = calls();
    render(<PlanAdaptation block={block()} onChanged={() => {}} failed />);
    fireEvent.change(screen.getByLabelText('Ask for a change to the plan'), { target: { value: ' skip the tests ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Suggest a change' }));
    await waitFor(() => expect(seen.length).toBe(1));
    expect(seen[0]).toEqual({ url: '/v1/blocks/blk/replan', body: { trigger: 'instruction', instruction: 'skip the tests' } });
    fireEvent.click(screen.getByRole('button', { name: 'Suggest a new plan for what failed' }));
    await waitFor(() => expect(seen.length).toBe(2));
    expect(seen[1].body).toEqual({ trigger: 'failure' });
  });

  it('offers the failure button only when a phase failed', () => {
    calls();
    render(<PlanAdaptation block={block({ run_status: 'running' })} onChanged={() => {}} failed={false} />);
    expect(screen.queryByRole('button', { name: /new plan for what failed/ })).toBeNull();
  });

  it('turns automatic revision on and says its limit', async () => {
    const seen = calls();
    render(<PlanAdaptation block={block({ replan: { auto: false, auto_used: 1, auto_limit: 2 } })} onChanged={() => {}} failed={false} />);
    expect(screen.getByText(/at most 2 times/).textContent).toMatch(/used 1/);
    fireEvent.click(screen.getByRole('checkbox'));
    await waitFor(() => expect(seen.length).toBe(1));
    expect(seen[0]).toEqual({ url: '/v1/blocks/blk/auto-replan', body: { enabled: true } });
  });

  it('shows why a revision failed, and no controls once the plan is over', () => {
    calls();
    const { rerender } = render(<PlanAdaptation block={block({ proposals: [proposal({ state: 'failed', summary: '"Analyze" has already finished, so it cannot be changed.', diff: null })] })} onChanged={() => {}} failed />);
    expect(screen.getByRole('status').textContent).toMatch(/already finished/);
    rerender(<PlanAdaptation block={block({ run_status: 'completed' })} onChanged={() => {}} failed={false} />);
    expect(screen.queryByLabelText('Ask for a change to the plan')).toBeNull(); expect(screen.queryByRole('checkbox')).toBeNull();
  });

  it('says what is wrong when the plan changed under it', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => (url === '/v1/csrf' ? reply({ csrf_token: 't' }) : reply({ error: 'version_conflict' }, 409))));
    render(<PlanAdaptation block={block({ proposals: [proposal()] })} onChanged={() => {}} failed />);
    fireEvent.click(screen.getByRole('button', { name: 'Apply this change' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/no longer possible/);
  });
});
