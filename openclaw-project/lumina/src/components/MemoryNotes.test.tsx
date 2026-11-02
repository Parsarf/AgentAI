import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import MemoryNotes from './MemoryNotes';
import { api } from '../lib/api';

vi.mock('../lib/api', async importOriginal => ({ ...await importOriginal<object>(), api: vi.fn() }));

let server: { available: boolean; memories: { id: string; kind: string; content: string; created: number }[] }, pending: boolean, fail: boolean;
const posts = () => vi.mocked(api).mock.calls.filter(c => c[0] === 'POST');

beforeEach(() => {
  pending = false; fail = false;
  server = { available: true, memories: [{ id: 'a'.repeat(32), kind: 'preference', content: 'Prefers aisle seats', created: 1 }, { id: 'b'.repeat(32), kind: 'fact', content: 'Works in the Berlin office', created: 2 }] };
  vi.mocked(api).mockImplementation(async (method, path) => {
    if (method === 'GET') return JSON.parse(JSON.stringify(server)) as any;
    if (fail) throw new Error('down');
    if (path === '/v1/longterm-memory/forget-all') { server.memories = []; return { ok: true, pending } as any; }
    const m = /\/v1\/longterm-memory\/(\w+)\/forget/.exec(path);
    if (m) { server.memories = server.memories.filter(x => x.id !== m[1]); return { ok: true, pending } as any; }
    return {} as any;
  });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('Settings → Memory', () => {
  it('is not on the page when the server says it is not available', async () => {
    server = { available: false, memories: [] };
    const { container } = render(<MemoryNotes />);
    await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
    expect(container.innerHTML).toBe('');
  });

  it('lists every note with its kind', async () => {
    render(<MemoryNotes />);
    expect(await screen.findByText('Prefers aisle seats')).toBeTruthy();
    expect(screen.getByText('Works in the Berlin office')).toBeTruthy();
    expect(screen.getByText('Preference:')).toBeTruthy();
  });

  it('deletes one note and leaves the others', async () => {
    render(<MemoryNotes />);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete note: Prefers aisle seats' }));
    await waitFor(() => expect(screen.queryByText('Prefers aisle seats')).toBeNull());
    expect(screen.getByText('Works in the Berlin office')).toBeTruthy();
    expect(posts()[0][1]).toBe(`/v1/longterm-memory/${'a'.repeat(32)}/forget`);
  });

  it('asks twice before deleting everything, and Cancel changes nothing', async () => {
    render(<MemoryNotes />);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete everything' }));
    expect(posts()).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.getByRole('button', { name: 'Delete everything' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Delete everything' }));
    fireEvent.click(screen.getByRole('button', { name: 'Yes, delete everything' }));
    expect(await screen.findByText('Nothing saved yet.')).toBeTruthy();
    expect(posts()).toEqual([['POST', '/v1/longterm-memory/forget-all', {}]]);
  });

  it('says plainly when the search copy is still being cleared', async () => {
    pending = true;
    render(<MemoryNotes />);
    fireEvent.click(await screen.findByRole('button', { name: 'Delete note: Prefers aisle seats' }));
    expect((await screen.findByRole('status')).textContent).toMatch(/still finishing/);
    expect(screen.queryByText('Prefers aisle seats')).toBeNull();
  });

  it('shows a message and keeps the list when a delete fails', async () => {
    render(<MemoryNotes />);
    const button = await screen.findByRole('button', { name: 'Delete note: Prefers aisle seats' });
    fail = true; fireEvent.click(button);
    expect((await screen.findByRole('alert')).textContent).toMatch(/Could not delete/);
    expect(screen.getByText('Prefers aisle seats')).toBeTruthy();
  });
});
