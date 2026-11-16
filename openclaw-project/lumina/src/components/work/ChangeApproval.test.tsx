import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Prompts, { ChangeApproval, Question, WorkflowApproval, waitWords } from './ChangeApproval';
import type { ActionNeed, ChangePreview, QuestionNeed, WorkflowNeed } from '../../lib/work';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const calls: { url: string; body: any }[] = [];
const server = (answer: (url: string) => Promise<Response>) => { calls.length = 0; vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
  if (url === '/v1/csrf') return reply({ csrf_token: 't' });
  calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null }); return answer(url); })); };
const preview = (over: Partial<ChangePreview> = {}): ChangePreview => ({ title: 'Change a note', destination: 'Synthetic service, note "Plan"', summary: 'Change the note "Plan"', affected: 1,
  changes: [{ field: 'body', before: 'Old text', after: 'New text' }], irreversible: null, can_undo: true, undo_seconds: 3600, compensations: [], ...over });
const soon = Math.floor(Date.now() / 1000) + 3 * 86400;
const action = (over: Partial<ActionNeed> = {}): ActionNeed => ({ kind: 'action', id: 'a1', payload_hash: 'h'.repeat(64), preview: preview(), needs_admin: false, approved_by_you: false, expires_epoch: soon, ...over });

describe('ChangeApproval', () => {
  it('shows where it goes, what changes before and after, and that nothing has been sent', () => {
    render(<ChangeApproval need={action()} />);
    expect(screen.getByText(/Nothing has been sent/)).toBeTruthy();
    expect(screen.getByText('Change the note "Plan"')).toBeTruthy();
    expect(screen.getByText(/Goes to: Synthetic service, note "Plan"/)).toBeTruthy();
    expect(screen.getByText('Old text')).toBeTruthy(); expect(screen.getByText('New text')).toBeTruthy();
    expect(screen.getByText(/Can be undone for 60 minutes/)).toBeTruthy();
    expect(screen.getByText(/If you do not decide, nothing is done/)).toBeTruthy();
  });

  it('says plainly what cannot be taken back, and what Lumina can offer instead', () => {
    render(<ChangeApproval need={action({ preview: preview({ summary: 'Send a message to sam', irreversible: 'A message that has been sent cannot be taken back.', can_undo: false, undo_seconds: null,
      compensations: [{ kind: 'message.correction', label: 'Send a correction' }] }) })} />);
    const warning = screen.getByRole('note');
    expect(warning.textContent).toContain('Cannot be taken back.'); expect(warning.textContent).toContain('send a correction');
    expect(screen.queryByText(/Can be undone/)).toBeNull();
  });

  it('approves exactly the payload that was shown, by its hash', async () => {
    server(() => reply({ action: { state: 'approved', needs_admin: false } }));
    render(<ChangeApproval need={action()} />);
    fireEvent.click(screen.getByText('Approve this change'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('Lumina is making the change now'));
    expect(calls).toEqual([{ url: '/v1/actions/a1/approve', body: { payload_hash: 'h'.repeat(64) } }]);
  });

  it('declines without sending a hash, and says nothing was changed', async () => {
    server(() => reply({ action: { state: 'declined', needs_admin: false } }));
    render(<ChangeApproval need={action()} />);
    fireEvent.click(screen.getByText('Decline'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toBe('Declined. Nothing was changed.'));
    expect(calls[0]).toEqual({ url: '/v1/actions/a1/decline', body: {} });
  });

  it('says so when the change is no longer the one that was shown', async () => {
    server(() => reply({ error: 'request_conflict' }, 409));
    render(<ChangeApproval need={action()} />);
    fireEvent.click(screen.getByText('Approve this change'));
    expect((await screen.findByRole('alert')).textContent).toContain('Nothing was done');
  });

  it('tells a member that their organization asks for an admin as well', async () => {
    server(() => reply({ action: { state: 'proposed', needs_admin: true } }));
    render(<ChangeApproval need={action({ needs_admin: true })} />);
    expect(screen.getByText(/asks for an admin to approve this as well/)).toBeTruthy();
    fireEvent.click(screen.getByText('Approve this change'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('An admin of your organization has to approve it as well'));
    cleanup();
    render(<ChangeApproval need={action({ needs_admin: true, approved_by_you: true })} />);
    expect(screen.queryByText('Approve this change')).toBeNull();
  });
});

describe('WorkflowApproval', () => {
  const need: WorkflowNeed = { kind: 'workflow', id: 'w1', title: 'Set up the project', steps_hash: 's'.repeat(64), expires_epoch: soon,
    steps: [preview({ summary: 'Create the note "One"' }), preview({ summary: 'Send a message to sam', irreversible: 'A message that has been sent cannot be taken back.', can_undo: false })] };
  it('shows every step and one approval covers them all', async () => {
    server(() => reply({ workflow: { state: 'approved' } }));
    render(<WorkflowApproval need={need} />);
    expect(screen.getByText('Create the note "One"')).toBeTruthy(); expect(screen.getByText('Send a message to sam')).toBeTruthy();
    expect(screen.getByText(/the step that cannot be taken back runs last/)).toBeTruthy();
    fireEvent.click(screen.getByText('Approve all 2'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('If one fails, the finished ones are reversed'));
    expect(calls[0]).toEqual({ url: '/v1/workflows/w1/approve', body: { steps_hash: 's'.repeat(64) } });
  });
});

describe('Question', () => {
  const need: QuestionNeed = { kind: 'question', id: 'q1', question: 'Which folder should I use?', options: ['Inbox', 'Projects'], expires_epoch: soon };
  it('answers with an option or with typed words', async () => {
    server(() => reply({ handoff: { state: 'answered' } }));
    render(<Question need={need} />);
    fireEvent.click(screen.getByText('Projects'));
    await waitFor(() => expect(screen.getByRole('status').textContent).toContain('carrying on'));
    expect(calls[0]).toEqual({ url: '/v1/handoffs/q1/answer', body: { answer: 'Projects' } });
    cleanup();
    render(<Question need={{ ...need, options: [] }} />);
    const send = screen.getByText('Answer') as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText('Your answer'), { target: { value: ' the archive ' } });
    fireEvent.click(send);
    await waitFor(() => expect(calls[1]).toEqual({ url: '/v1/handoffs/q1/answer', body: { answer: 'the archive' } }));
  });
});

describe('Prompts', () => {
  it('renders each kind that is answered where the task is shown, and nothing for the others', () => {
    render(<Prompts needs={[action(), { kind: 'question', id: 'q1', question: 'Why?', options: [], expires_epoch: soon }, { kind: 'location_permission' }]} />);
    expect(screen.getByText('Approve this change')).toBeTruthy(); expect(screen.getByText('Why?')).toBeTruthy();
    expect(screen.getAllByRole('group').length).toBe(2);
  });
  it('says how long it waits in words', () => {
    expect(waitWords(1000 + 3 * 86400, 1000)).toBe('Waits 3 more days for you');
    expect(waitWords(1000 + 5 * 3600, 1000)).toBe('Waits 5 more hours for you');
    expect(waitWords(1000 + 600, 1000)).toBe('Waits 10 more minutes for you');
  });
});
