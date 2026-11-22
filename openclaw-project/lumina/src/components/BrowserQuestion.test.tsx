import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import BrowserQuestion from './BrowserQuestion';
import { api } from '../lib/api';

vi.mock('../lib/api', () => ({ api: vi.fn().mockResolvedValue({ ok: true }) }));
const sent = () => (api as unknown as ReturnType<typeof vi.fn>).mock.calls;
afterEach(() => { vi.clearAllMocks(); });

describe("a question from Lumina's browser", () => {
  it('shows the choices the server offers and answers with the one the customer picks', async () => {
    const done = vi.fn();
    render(<BrowserQuestion id="r1" onAnswered={done} question={{ id: 'q1', title: 'Which size do you want?', field: 'size', menu: true, kind: 'choice', options: [{ id: 'o1', label: 'Small' }, { id: 'o2', label: 'Medium' }] }} />);
    expect(screen.getByText('Which size do you want?')).toBeTruthy();
    fireEvent.click(screen.getByText('Medium'));
    await waitFor(() => expect(done).toHaveBeenCalled());
    expect(sent()[0]).toEqual(['POST', '/v1/browse/r1/answer', { question_id: 'q1', option: 'o2' }]);
  });

  it('lets the customer choose on the page instead when the question allows it', async () => {
    render(<BrowserQuestion id="r1" onAnswered={() => {}} question={{ id: 'q1', title: '', field: '', menu: true, options: [] }} />);
    expect(screen.getByText('Which one do you want?')).toBeTruthy();
    fireEvent.click(screen.getByText('I chose on the page, continue'));
    await waitFor(() => expect(sent().length).toBe(1));
    expect(sent()[0][2]).toEqual({ question_id: 'q1', resume: true });
  });

  it('asks permission for one button in plain words and offers no way round it', () => {
    render(<BrowserQuestion id="r1" onAnswered={() => {}} question={{ id: 'q9', title: 'Lumina wants to press "Remove" on shop.example. Allow it?', field: '', menu: false, use: 'approval',
      options: [{ id: 'o1', label: 'Yes, press it' }, { id: 'o2', label: 'No, I will do it myself' }] }} />);
    expect(screen.getByText('Lumina needs your permission')).toBeTruthy(); expect(screen.getByText('Yes, press it')).toBeTruthy();
    expect(screen.queryByText('I chose on the page, continue')).toBeNull();
  });

  it('collects the details a form needs, never a field marked sensitive, and sends only what was filled in', async () => {
    render(<BrowserQuestion id="r1" onAnswered={() => {}} question={{ id: 'q2', title: 'A few details are needed', field: '', menu: true, kind: 'fields', options: [],
      fields: [{ id: 'f1', label: 'Full name', key: 'full name', sensitive: false, input_type: 'text', prefill: 'Jordan Lee' }, { id: 'f2', label: 'Phone', key: 'phone', sensitive: false, input_type: 'tel' },
        { id: 'f3', label: 'Card number', key: 'card number', sensitive: true, input_type: 'text' }] }} />);
    expect((screen.getByLabelText('Full name') as HTMLInputElement).value).toBe('Jordan Lee');
    expect(screen.queryByLabelText('Card number')).toBeNull(); expect(screen.getByText(/Card number: type this one into the page yourself/)).toBeTruthy();
    fireEvent.click(screen.getByText('Fill these in'));
    await waitFor(() => expect(sent().length).toBe(1));
    expect(sent()[0][2]).toEqual({ question_id: 'q2', fields: { f1: 'Jordan Lee' } });
  });

  it('says so when the answer did not go through, and stays', async () => {
    (api as unknown as ReturnType<typeof vi.fn>).mockRejectedValueOnce(new Error('409'));
    const done = vi.fn();
    render(<BrowserQuestion id="r1" onAnswered={done} question={{ id: 'q1', title: 'Pick', field: '', menu: false, options: [{ id: 'o1', label: 'A' }, { id: 'o2', label: 'B' }] }} />);
    fireEvent.click(screen.getByText('A'));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toContain('did not go through'));
    expect(done).not.toHaveBeenCalled();
  });
});
