import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ChatQuestion from './ChatQuestion';
import { api } from '../lib/api';

vi.mock('../lib/api', () => ({ api: vi.fn() }));
const asking = { status: 'asking', question: { id: 'q1', title: 'Which size?', field: 'size', menu: true, options: [{ id: 'o1', label: 'Small' }, { id: 'o2', label: 'Medium' }] } };
const fieldsQ = { status: 'asking', question: { id: 'q2', title: 'Your details', field: '', menu: true, kind: 'fields', options: [], fields: [{ id: 'f1', label: 'Full name', key: 'full name', sensitive: false, input_type: 'text', prefill: '' }] } };
const Where = () => <span data-testid="where">{useLocation().pathname + useLocation().search}</span>;
const mount = () => render(<MemoryRouter><ChatQuestion taskId="t1" active /><Routes><Route path="*" element={<Where />} /></Routes></MemoryRouter>);
afterEach(() => { vi.clearAllMocks(); });

describe('the browser question in the chat', () => {
  it('shows nothing for a task with no browser, or one that is not asking', async () => {
    vi.mocked(api).mockRejectedValue(new Error('404'));
    const { container } = mount(); await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(container.querySelector('.chat-question')).toBeNull();
  });

  it('shows a choice under the message and sends the answer to the right task', async () => {
    vi.mocked(api).mockImplementation(async (method: string) => (method === 'GET' ? asking : { ok: true }) as any);
    mount(); fireEvent.click(await screen.findByText('Medium')); fireEvent.click(screen.getByText('Use this'));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/browse/t1/answer', { question_id: 'q1', option: 'o2', remember: false }));
  });

  it('shows the details box, and "enter it myself" opens the Live view with the page ready', async () => {
    vi.mocked(api).mockImplementation(async () => fieldsQ as any);
    mount(); await screen.findByLabelText('Full name');
    fireEvent.click(screen.getByText(/enter these myself on the page/));
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/live/t1?hands=1'));
  });

  it('cancelling stops the task', async () => {
    vi.mocked(api).mockImplementation(async (method: string, path: string) => (method === 'GET' ? fieldsQ : { ok: path }) as any);
    mount(); await screen.findByLabelText('Full name'); fireEvent.click(screen.getByText('Cancel'));
    await waitFor(() => expect(api).toHaveBeenCalledWith('POST', '/v1/requests/t1/cancel', {}));
  });
});
