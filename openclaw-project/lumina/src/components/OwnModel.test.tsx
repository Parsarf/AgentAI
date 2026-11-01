import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import OwnModel from './OwnModel';
import { api, ApiError } from '../lib/api';

vi.mock('../lib/api', async importOriginal => ({ ...await importOriginal<object>(), api: vi.fn() }));

let server: { available: boolean; configured: boolean; host?: string; model?: string; hint?: string }, saveError: ApiError | null;
const posts = () => vi.mocked(api).mock.calls.filter(c => c[0] === 'POST');
const fill = async () => {
  fireEvent.change(await screen.findByLabelText(/Endpoint address/), { target: { value: 'https://api.openai.com/v1' } });
  fireEvent.change(screen.getByLabelText(/Model name/), { target: { value: 'gpt-4o-mini' } });
  fireEvent.change(screen.getByLabelText(/API key/), { target: { value: 'sk-secret-1234' } });
};

beforeEach(() => {
  server = { available: true, configured: false }; saveError = null;
  vi.mocked(api).mockImplementation(async (method, path, body: any) => {
    if (method === 'GET') return { ...server } as any;
    if (path === '/v1/model-key/save') {
      if (saveError) throw saveError;
      server = { available: true, configured: true, host: 'api.openai.com', model: body.model, hint: '1234' };
      return { ...server, applies: 'the next time your assistant starts' } as any;
    }
    if (path === '/v1/model-key/remove') { server = { available: true, configured: false }; return { configured: false } as any; }
    return {} as any;
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('Settings → Your own model', () => {
  it('is not on the page when the server says it is not available', async () => {
    server.available = false;
    const { container } = render(<OwnModel />);
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
    expect(container.innerHTML).toBe('');
  });

  it('sends the address, model and key once, then forgets the key and shows only the last four characters', async () => {
    render(<OwnModel />); await fill();
    fireEvent.click(screen.getByRole('button', { name: 'Test and save' }));
    expect(await screen.findByText(/key ending in/)).toBeTruthy();
    expect(posts()[0]).toEqual(['POST', '/v1/model-key/save', { base_url: 'https://api.openai.com/v1', api_key: 'sk-secret-1234', model: 'gpt-4o-mini' }]);
    expect(document.body.innerHTML).not.toContain('sk-secret-1234');
    expect(screen.getByText('1234')).toBeTruthy();
    expect(screen.getByRole('status').textContent).toContain('the next time your assistant starts');
  });

  it('shows the server’s reason when the key does not work, and keeps the form', async () => {
    saveError = new ApiError('model_key_invalid', 422, undefined, 'The company refused the key.');
    render(<OwnModel />); await fill();
    fireEvent.click(screen.getByRole('button', { name: 'Test and save' }));
    expect((await screen.findByRole('alert')).textContent).toBe('The company refused the key.');
    expect(screen.getByRole('button', { name: 'Test and save' })).toBeTruthy();
  });

  it('says to wait when rate limited', async () => {
    saveError = new ApiError('rate_limited', 429);
    render(<OwnModel />); await fill();
    fireEvent.click(screen.getByRole('button', { name: 'Test and save' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/Wait a few minutes/);
  });

  it('fills a common address from a preset', async () => {
    render(<OwnModel />);
    fireEvent.click(await screen.findByRole('button', { name: 'OpenRouter' }));
    expect((screen.getByLabelText(/Endpoint address/) as HTMLInputElement).value).toBe('https://openrouter.ai/api/v1');
  });

  it('removes a saved key', async () => {
    server = { available: true, configured: true, host: 'api.openai.com', model: 'gpt-4o-mini', hint: '1234' };
    render(<OwnModel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Remove my key' }));
    expect(await screen.findByRole('button', { name: 'Test and save' })).toBeTruthy();
    expect(posts()[0][1]).toBe('/v1/model-key/remove');
  });
});
