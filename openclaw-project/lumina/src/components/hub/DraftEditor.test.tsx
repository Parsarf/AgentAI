import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import DraftEditor from './DraftEditor';
import { hub, type Draft } from '../../lib/hub';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const draft: Draft = { id: 'd1', account: 'c1', thread: 't1', to: ['ann@x.test'], cc: [], subject: 'Re: Invoice', body: 'Thanks, paid today.', origin: 'assistant', created_epoch: 1, updated_epoch: 2 };

describe('DraftEditor', () => {
  it('saves a new reply in Lumina only and says that nothing was sent', async () => {
    const save = vi.spyOn(hub, 'saveDraft').mockResolvedValue({ draft: { ...draft, id: 'd2', origin: 'customer' } });
    const saved = vi.fn();
    render(<DraftEditor start={{ account: 'c1', thread: 't1', to: ['ann@x.test'], subject: 'Re: Invoice' }} accountLabel="me@x.test" canOpenInService onSaved={saved} onDiscarded={() => undefined} />);
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Hello' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(save).toHaveBeenCalledWith({ connection_id: 'c1', thread_id: 't1', to: ['ann@x.test'], cc: [], subject: 'Re: Invoice', body: 'Hello' }));
    expect(saved).toHaveBeenCalled();
    expect(await screen.findByText('Saved in Lumina. Nothing was sent.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /^Send/ })).toBeNull();
  });
  it('opens the draft in the mail service\'s own compose screen, and only offers that where the account has one', async () => {
    vi.spyOn(hub, 'composeLink').mockResolvedValue({ draft, link: 'https://mail.example.test/compose?x=1' });
    const opened = vi.spyOn(window, 'open').mockReturnValue(null);
    const { rerender } = render(<DraftEditor draft={draft} accountLabel="me@x.test" canOpenInService onSaved={() => undefined} onDiscarded={() => undefined} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open in your mail service' }));
    await waitFor(() => expect(opened).toHaveBeenCalledWith('https://mail.example.test/compose?x=1', '_blank', 'noopener,noreferrer'));
    rerender(<DraftEditor draft={draft} accountLabel="me@x.test" canOpenInService={false} onSaved={() => undefined} onDiscarded={() => undefined} />);
    expect(screen.queryByRole('button', { name: 'Open in your mail service' })).toBeNull();
  });
  it('takes the assistant\'s newer version unless the customer is editing, and discards only after asking', async () => {
    const discard = vi.spyOn(hub, 'discardDraft').mockResolvedValue({ discarded: 'd1' });
    const gone = vi.fn();
    const { rerender } = render(<DraftEditor draft={draft} accountLabel="me@x.test" canOpenInService onSaved={() => undefined} onDiscarded={gone} />);
    rerender(<DraftEditor draft={{ ...draft, body: 'Shorter.', updated_epoch: 3 }} accountLabel="me@x.test" canOpenInService onSaved={() => undefined} onDiscarded={gone} />);
    expect((screen.getByLabelText('Message') as HTMLTextAreaElement).value).toBe('Shorter.');
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Mine' } });
    rerender(<DraftEditor draft={{ ...draft, body: 'Even shorter.', updated_epoch: 4 }} accountLabel="me@x.test" canOpenInService onSaved={() => undefined} onDiscarded={gone} />);
    expect((screen.getByLabelText('Message') as HTMLTextAreaElement).value).toBe('Mine');
    fireEvent.click(screen.getByRole('button', { name: 'Discard' }));
    expect(discard).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole('button', { name: 'Discard' })[1]);
    await waitFor(() => expect(gone).toHaveBeenCalledWith('d1'));
  });
});
