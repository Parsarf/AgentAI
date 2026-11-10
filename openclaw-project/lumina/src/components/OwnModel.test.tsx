import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import OwnModel from './OwnModel';
import { api, ApiError } from '../lib/api';
vi.mock('../lib/api', async original => ({ ...await original<object>(), api: vi.fn() }));
const keys = [{ id: 'key:one', host: 'models.example.org', model: 'my-model', hint: '1234' }, { id: 'key:two', host: 'models.example.org', model: 'other-model', hint: '5678' }];
let server: any, failure: ApiError | null;
const posts = () => vi.mocked(api).mock.calls.filter(c => c[0] === 'POST');
beforeEach(() => {
  server = { available: true, configured: false, selected: 'lumina-default', keys: [], lumina_models: [{ id: 'lumina-default', name: 'Lumina' }] }; failure = null;
  vi.mocked(api).mockImplementation(async (method, path, body: any) => {
    if (method === 'GET') return structuredClone(server);
    if (failure) throw failure;
    if (path.endsWith('/save')) server = { ...server, configured: true, keys: [...server.keys, keys[0]] };
    if (path.endsWith('/select')) server.selected = body.id;
    if (path.endsWith('/remove')) server.keys = server.keys.filter((k: any) => k.id !== body.id);
    return structuredClone(server);
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const fill = async () => {
  fireEvent.change(await screen.findByLabelText('Endpoint address'), { target: { value: 'https://api.openai.com/v1' } });
  fireEvent.change(screen.getByLabelText('Model name'), { target: { value: 'my-model' } });
  fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'sk-secret-1234' } });
};
describe('Models', () => {
  it('keeps Lumina available when personal keys are disabled', async () => {
    server.available = false; render(<OwnModel />);
    expect(await screen.findByLabelText('Assistant model')).toBeTruthy();
    expect(screen.queryByLabelText('API key')).toBeNull();
  });
  it('adds a key without changing selection or exposing its secret', async () => {
    render(<OwnModel />); await fill(); fireEvent.click(screen.getByText('Test and save'));
    expect(await screen.findByText(/key ending in/)).toBeTruthy();
    expect(posts()[0]).toEqual(['POST', '/v1/model-key/save', { base_url: 'https://api.openai.com/v1', model: 'my-model', api_key: 'sk-secret-1234' }]);
    expect((screen.getByLabelText('Assistant model') as HTMLSelectElement).value).toBe('lumina-default');
    expect((screen.getByLabelText('API key') as HTMLInputElement).value).toBe('');
    expect(document.body.innerHTML).not.toContain('sk-secret-1234');
  });
  it('switches between keys and back to Lumina without deleting any key', async () => {
    server.keys = keys; server.configured = true; render(<OwnModel />);
    const select = await screen.findByLabelText('Assistant model');
    for (const id of ['key:one', 'key:two', 'lumina-default']) {
      fireEvent.change(select, { target: { value: id } }); fireEvent.click(screen.getByText('Use model'));
      await waitFor(() => expect(server.selected).toBe(id)); await waitFor(() => expect((screen.getByText('Use model') as HTMLButtonElement).disabled).toBe(true));
    }
    expect(server.keys).toHaveLength(2); expect(posts().every(c => c[1].endsWith('/select'))).toBe(true);
  });
  it('renders new Lumina models from the server catalog', async () => {
    server.lumina_models.push({ id: 'lumina-future', name: 'Future model' }); render(<OwnModel />);
    expect(await screen.findByRole('option', { name: 'Future model' })).toBeTruthy();
  });
  it('removes only the chosen key', async () => {
    server.keys = keys; render(<OwnModel />);
    fireEvent.click(await screen.findByRole('button', { name: 'Remove my-model key ending 1234' }));
    await waitFor(() => expect(server.keys).toHaveLength(1));
    expect(posts()[0]).toEqual(['POST', '/v1/model-key/remove', { id: 'key:one' }]);
  });
  it('shows busy-task rejection without pretending the model changed', async () => {
    server.keys = keys; render(<OwnModel />); const select = await screen.findByLabelText('Assistant model');
    failure = new ApiError('model_busy', 409, undefined, 'Finish or stop your pending tasks before changing models or keys.');
    fireEvent.change(select, { target: { value: 'key:one' } }); fireEvent.click(screen.getByText('Use model'));
    expect((await screen.findByRole('alert')).textContent).toContain('Finish or stop'); expect(server.selected).toBe('lumina-default');
    expect((select as HTMLSelectElement).value).toBe('lumina-default');
  });
  it('clears the secret after a failed save', async () => {
    failure = new ApiError('invalid_key', 422, undefined, 'Provider refused this key.'); render(<OwnModel />); await fill();
    fireEvent.click(screen.getByText('Test and save')); expect((await screen.findByRole('alert')).textContent).toBe('Provider refused this key.');
    expect((screen.getByLabelText('API key') as HTMLInputElement).value).toBe('');
  });
  it('loads settings under StrictMode without losing mounted state', async () => {
    const { StrictMode } = await import('react'); render(<StrictMode><OwnModel /></StrictMode>);
    expect(await screen.findByLabelText('Assistant model')).toBeTruthy();
  });
});
