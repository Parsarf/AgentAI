import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FileCard from './FileCard';
import AnswerSave, { filesOf } from './AnswerSave';
import Files from '../../pages/Files';

const app = { features: { files: true, convert: true } };
vi.mock('../../state/data', () => ({ useData: () => ({ app }) }));
const calls: { method: string; path: string; body?: unknown }[] = [];
let files: any[] = [];
vi.mock('../../lib/api', async original => ({
  ...(await original<typeof import('../../lib/api')>()),
  csrfToken: async () => 'csrf',
  api: vi.fn(async (method: string, path: string, body?: unknown) => {
    calls.push({ method, path, body });
    if (path === '/v1/files') return { files, used_bytes: 1500, quota_bytes: 2 * 1073741824 };
    if (path.endsWith('/ticket')) return { download: { path: '/v1/artifacts/x/versions/1/download?ticket=t' } };
    if (path.endsWith('/delete')) { files = files.filter(f => !path.includes(f.id)); return { deleted: {} }; }
    if (path === '/v1/files/bundle') return { bundle: { artifact_id: 'zip', version: 1 } };
    return {};
  }),
}));

const row = (id: string, version: number, name: string, extra = {}) => ({ id, version, display_name: name, media_type: 'application/octet-stream', size_bytes: 2048, created_at: `2026-11-1${version}T10:00:00Z`, task_id: 't1', conversation_id: 'c1', ...extra });
const assign = vi.fn();
beforeEach(() => { calls.length = 0; files = []; assign.mockReset(); Object.defineProperty(window, 'location', { value: { ...window.location, assign }, writable: true }); });
afterEach(cleanup);

describe('file card', () => {
  it('shows what the file is and downloads it through a ticket', async () => {
    render(<FileCard file={row('a', 2, 'reports/Q3 sales.xlsx')} />);
    expect(screen.getByText('Q3 sales.xlsx')).toBeTruthy();
    expect(screen.getByText(/Spreadsheet · 2.0 KB · version 2/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Download/ }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith('/v1/artifacts/x/versions/1/download?ticket=t'));
    expect(calls[0]).toMatchObject({ method: 'POST', path: '/v1/artifacts/a/versions/2/ticket' });
  });
  it('offers a preview only where there is one, as a picture of the first page', () => {
    render(<FileCard file={row('a', 1, 'deck.pptx')} />);
    expect(screen.queryByRole('img')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    expect(screen.getByRole('img', { name: 'Preview of deck.pptx' }).getAttribute('src')).toBe('/v1/artifacts/a/versions/1/preview');
    cleanup();
    render(<FileCard file={row('b', 1, 'backup.zip')} />);
    expect(screen.queryByRole('button', { name: 'Preview' })).toBeNull();
  });
  it('lists the newest version of each file a task made, never the download-all archive', () => {
    const made = [row('a', 1, 'a.pdf'), row('a', 2, 'a.pdf'), row('b', 1, 'b.xlsx'), row('z', 1, 'project-all-bundle.zip'), row('c', 1, 'c.md', { task_id: 'other' })];
    expect(filesOf(made, 't1').map(f => [f.id, f.version])).toEqual([['b', 1], ['a', 2]]);
    expect(filesOf(made, null)).toEqual([]);
  });
});

describe('download as', () => {
  it('asks the server for the answer in the format picked and saves what comes back', async () => {
    const fetched = vi.fn(async () => new Response(new Blob(['%PDF']), { status: 200, headers: { 'Content-Disposition': 'attachment; filename="Trip plan.pdf"' } }));
    vi.stubGlobal('fetch', fetched); URL.createObjectURL = vi.fn(() => 'blob:x'); URL.revokeObjectURL = vi.fn();
    const onError = vi.fn();
    render(<AnswerSave conversation="c1" message={7} convert onError={onError} />);
    fireEvent.click(screen.getByRole('button', { name: 'Download this answer as' }));
    expect(screen.getAllByRole('menuitem').map(i => i.textContent)).toEqual(['PDF', 'Word document', 'Markdown', 'Plain text']);
    fireEvent.click(screen.getByRole('menuitem', { name: 'PDF' }));
    await waitFor(() => expect(fetched).toHaveBeenCalled());
    const [path, init] = fetched.mock.calls[0] as unknown as [string, RequestInit];
    expect(path).toBe('/v1/conversations/c1/export');
    expect(JSON.parse(String(init.body))).toEqual({ format: 'pdf', message: '7' });
    expect((init.headers as Record<string, string>)['X-CSRFToken']).toBe('csrf');
    await waitFor(() => expect(URL.createObjectURL).toHaveBeenCalled());          // the download ran to the end
    expect(onError.mock.calls).toEqual([]);
    vi.unstubAllGlobals();
  });
  it('offers only the formats that need no converter when there is none, and says why a download failed', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ error: 'convert_not_available' }), { status: 503 })));
    const onError = vi.fn();
    render(<AnswerSave conversation="c1" convert={false} onError={onError} />);
    fireEvent.click(screen.getByRole('button', { name: 'Download this answer as' }));
    expect(screen.getAllByRole('menuitem').map(i => i.textContent)).toEqual(['Markdown', 'Plain text']);
    fireEvent.click(screen.getByRole('menuitem', { name: 'Markdown' }));
    await waitFor(() => expect(onError).toHaveBeenCalledWith('That format is not available right now. Markdown and plain text still work.'));
    vi.unstubAllGlobals();
  });
});

describe('files page', () => {
  const page = () => render(<MemoryRouter><Files /></MemoryRouter>);
  it('lists every file in one request, by folder, with storage used', async () => {
    files = [row('a', 1, 'reports/Q3 sales.xlsx'), row('b', 1, 'notes.md'), row('b', 2, 'notes.md'), row('z', 1, 'project-all-bundle.zip')];
    page();
    await screen.findByText('Q3 sales.xlsx');
    expect(calls.map(c => c.path)).toEqual(['/v1/files']);
    expect(screen.getByText('reports')).toBeTruthy();
    expect(screen.getByText(/Text · 2.0 KB · .* · version 2/)).toBeTruthy();
    expect(screen.queryByText(/bundle/)).toBeNull();
    expect(screen.getByText('1.5 KB of 2.00 GB used')).toBeTruthy();
    expect(screen.getAllByRole('link', { name: 'Open the chat' })[0].getAttribute('href')).toBe('/chat/c1');
    fireEvent.click(screen.getByRole('button', { name: 'Download all (.zip)' }));
    await waitFor(() => expect(calls.some(c => c.path === '/v1/artifacts/zip/versions/1/ticket')).toBe(true));
    expect(calls.some(c => c.path === '/v1/files/bundle')).toBe(true);
  });
  it('deletes only after the person confirms, then the file is gone from the list', async () => {
    files = [row('a', 1, 'old plan.pdf'), row('a', 2, 'old plan.pdf')];
    page();
    fireEvent.click(await screen.findByRole('button', { name: 'Delete old plan.pdf' }));
    expect(calls.some(c => c.path.endsWith('/delete'))).toBe(false);                 // nothing happens on the first click
    expect(screen.getByRole('alertdialog').textContent).toContain('and its 2 versions for good? This cannot be undone.');
    fireEvent.click(screen.getByRole('button', { name: 'Keep' }));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Delete old plan.pdf' }));
    fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(screen.queryByText('old plan.pdf')).toBeNull());
    expect(calls.find(c => c.path.endsWith('/delete'))).toMatchObject({ method: 'POST', path: '/v1/artifacts/a/delete' });
    expect(screen.getByText(/Nothing yet\. Ask Lumina for a file/)).toBeTruthy();
  });
  it('shows earlier versions and each can be downloaded', async () => {
    files = [row('a', 1, 'plan.zip'), row('a', 2, 'plan.zip')];
    page();
    fireEvent.click(await screen.findByRole('button', { name: 'Versions' }));
    expect(screen.getByText(/Version 2 · .* · newest/)).toBeTruthy();
    const older = screen.getByText(/^Version 1 ·/).parentElement!;
    fireEvent.click(older.querySelector('button')!);
    await waitFor(() => expect(calls.some(c => c.path === '/v1/artifacts/a/versions/1/ticket')).toBe(true));
  });
});
