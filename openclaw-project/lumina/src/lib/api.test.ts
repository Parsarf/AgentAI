import { afterEach, expect, it, vi } from 'vitest';
import { api, ApiError, resetCsrf } from './api';
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); resetCsrf(); });
it('bounds a stalled request, including CSRF acquisition', async () => {
  vi.useFakeTimers();
  vi.stubGlobal('fetch', vi.fn((_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))));
  const pending = api('POST', '/v1/genui/artifacts/test/state', {}, { timeoutMs: 15000 });
  const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  await vi.advanceTimersByTimeAsync(15000); await rejected;
});
it('preserves safe structured field errors and admission categories', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 400, json: async () => ({ error: 'invalid_ui_values', field_errors: { quantity: 'Enter a number within the allowed range.' } }) })));
  try { await api('GET', '/test'); throw new Error('expected refusal'); } catch (error) {
    expect(error).toBeInstanceOf(ApiError); expect((error as ApiError).fieldErrors).toEqual({ quantity: 'Enter a number within the allowed range.' });
  }
});
