import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import DraftEditor from './DraftEditor';
import { hub, type Draft, type HubAccount } from '../../lib/hub';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });
const draft: Draft = { id: 'd1', account: 'c1', thread: 't1', to: ['ann@x.test'], cc: [], subject: 'Re: Invoice', body: 'Thanks, paid today.', origin: 'assistant', created_epoch: 1, updated_epoch: 2 };
const account = (over: Partial<HubAccount['capabilities']> = {}, more: Partial<HubAccount> = {}): HubAccount => ({ id: 'c1', provider: 'first', provider_label: 'First Mail', identity: 'me@x.test', state: 'working', needs_reason: null,
  capabilities: { mail: true, calendar: true, mail_search: true, incremental: true, push: false, labels: 'labels', subjects: true, send: false, organize: false, mark_read: false, event_write: false, respond: false,
    compose_link: true, ...over }, granted: { mail: true, calendar: true }, mail: null, calendar: null, ...more });
const quiet = () => undefined;

describe('DraftEditor', () => {
  it('saves what is written by itself a moment after the last keystroke, in Lumina only', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    const save = vi.spyOn(hub, 'saveDraft').mockResolvedValue({ draft: { ...draft, id: 'd2', origin: 'customer', body: 'Hello' } });
    const saved = vi.fn();
    render(<DraftEditor start={{ account: 'c1', thread: 't1', to: ['ann@x.test'], subject: 'Re: Invoice' }} accounts={[account()]} writes={false} onSaved={saved} onDiscarded={quiet} />);
    expect(screen.getByRole('region', { name: 'Your reply' })).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Hel' } });
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Hello' } });
    expect(save).not.toHaveBeenCalled();                                                          // not on every keystroke
    await vi.advanceTimersByTimeAsync(1000);
    expect(save).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1000);
    vi.useRealTimers();
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(save).toHaveBeenCalledWith({ connection_id: 'c1', thread_id: 't1', to: ['ann@x.test'], cc: [], subject: 'Re: Invoice', body: 'Hello' });
    expect(saved).toHaveBeenCalled();
    expect(await screen.findByText('Saved in Lumina')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Send' })).toBeNull();                            // this account may not send from Lumina: no Send is drawn
    expect(screen.getByText(/Sending from Lumina is not on for this account yet/)).toBeTruthy();
  });

  it('opens the draft in the mail service\'s own compose screen where the account has one, and offers copying where it has none', async () => {
    vi.spyOn(hub, 'composeLink').mockResolvedValue({ draft, link: 'https://mail.example.test/compose?x=1' });
    const opened = vi.spyOn(window, 'open').mockReturnValue(null);
    const { rerender } = render(<DraftEditor draft={draft} accounts={[account()]} writes={false} onSaved={quiet} onDiscarded={quiet} />);
    fireEvent.click(screen.getByRole('button', { name: 'Open in your mail service' }));
    await waitFor(() => expect(opened).toHaveBeenCalledWith('https://mail.example.test/compose?x=1', '_blank', 'noopener,noreferrer'));
    rerender(<DraftEditor draft={draft} accounts={[account({ compose_link: false })]} writes={false} onSaved={quiet} onDiscarded={quiet} />);
    expect(screen.queryByRole('button', { name: 'Open in your mail service' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Copy the text' })).toBeTruthy();
  });

  it('takes the assistant\'s newer version unless the customer is editing, and discards only after asking', async () => {
    vi.spyOn(hub, 'saveDraft').mockResolvedValue({ draft: { ...draft, body: 'Mine' } });
    const discard = vi.spyOn(hub, 'discardDraft').mockResolvedValue({ discarded: 'd1' });
    const gone = vi.fn();
    const props = { accounts: [account()], writes: false, onSaved: quiet, onDiscarded: gone };
    const { rerender } = render(<DraftEditor draft={draft} {...props} />);
    expect(screen.getByRole('region', { name: 'Draft by your assistant' })).toBeTruthy();
    rerender(<DraftEditor draft={{ ...draft, body: 'Shorter.', updated_epoch: 3 }} {...props} />);
    expect((screen.getByLabelText('Message') as HTMLTextAreaElement).value).toBe('Shorter.');
    fireEvent.change(screen.getByLabelText('Message'), { target: { value: 'Mine' } });
    rerender(<DraftEditor draft={{ ...draft, body: 'Even shorter.', updated_epoch: 4 }} {...props} />);
    expect((screen.getByLabelText('Message') as HTMLTextAreaElement).value).toBe('Mine');
    fireEvent.click(screen.getByRole('button', { name: 'Discard this draft' }));
    expect(discard).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole('button', { name: 'Discard' }));
    await waitFor(() => expect(gone).toHaveBeenCalledWith('d1'));
  });

  it('suggests people from the customer\'s own mail while a recipient is typed, and takes one with the keyboard', async () => {
    const people = vi.spyOn(hub, 'people').mockResolvedValue({ people: [{ name: 'Ann Lee', address: 'ann@x.test' }, { name: 'Anders', address: 'anders@y.test' }] });
    vi.spyOn(hub, 'saveDraft').mockResolvedValue({ draft });
    render(<DraftEditor start={{ account: 'c1', thread: null, to: [], subject: '' }} accounts={[account()]} writes={false} onSaved={quiet} onDiscarded={quiet} />);
    const to = screen.getByLabelText('To') as HTMLInputElement;
    fireEvent.change(to, { target: { value: 'bo@z.test, an' } });
    const list = await screen.findByRole('listbox', { name: 'People for To' });
    expect(people).toHaveBeenCalledWith('an');                                                    // only the address being typed is looked up
    expect(list.textContent).toContain('Ann Lee'); expect(to.getAttribute('aria-expanded')).toBe('true');
    fireEvent.keyDown(to, { key: 'ArrowDown' }); fireEvent.keyDown(to, { key: 'Enter' });
    expect(to.value).toBe('bo@z.test, anders@y.test, ');
    expect(screen.queryByRole('listbox')).toBeNull();
  });

  it('lets a new message leave from any account, and offers the permission where an account may not send yet', async () => {
    const second = account({ send: true }, { id: 'c2', identity: 'ich@second.test' });
    const first = account({ send: false, missing: { send: 'send' } }, { grants: [{ name: 'send', capabilities: ['send'], words: 'Send email from this account, only when you press Send.' }] });
    render(<DraftEditor start={{ account: 'c1', thread: null, to: [], subject: '' }} accounts={[first, second]} writes onSaved={quiet} onDiscarded={quiet} />);
    expect(screen.getByRole('region', { name: 'New message' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Allow changes for me@x.test' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Send' })).toBeNull();
    fireEvent.change(screen.getByLabelText('From'), { target: { value: 'c2' } });
    expect(await screen.findByRole('button', { name: 'Send' })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Allow changes/ })).toBeNull();
  });
});
