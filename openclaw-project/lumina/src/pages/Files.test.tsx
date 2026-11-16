import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Files from './Files';
import type { Catalogue, CatalogueFile } from '../lib/files';

let features: Record<string, boolean> = { files: true };
vi.mock('../state/data', () => ({ useData: () => ({ app: { features } }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); features = { files: true }; });

const file = (over: Partial<CatalogueFile>): CatalogueFile => ({ kind: 'upload', id: 'u1', name: 'report.docx', original_name: 'report.docx', media_type: 'application/x', size_bytes: 20480, project_id: 'p1', folder_id: null,
  source: 'uploaded', created_at: '2026-11-10T10:00:00.000Z', family: 'document', copy_of: null, ...over });
const made = file({ kind: 'made', id: 'a1', name: 'summary.pdf', original_name: 'summary.pdf', source: 'made', version: 2, versions: 2, conversation_id: 'c1', created_at: '2026-11-12T10:00:00.000Z' });
const picture = file({ id: 'u2', name: 'photo.png', original_name: 'photo.png', family: 'picture', folder_id: 'f1', copy_of: { kind: 'upload', id: 'u9', name: 'old photo.png' } });
const catalogue = (over: Partial<Catalogue> = {}): Catalogue => ({ files: [made, file({}), picture], folders: [{ id: 'f1', project_id: 'p1', parent_id: null, name: 'Reports', files: 1 }],
  projects: [{ id: 'p1', name: 'General' }], total: 3, uploads: true, ...over });
const listing = { files: [{ id: 'a1', version: 2, display_name: 'summary.pdf', media_type: 'application/pdf', size_bytes: 20480, created_at: '2026-11-12T10:00:00.000Z' },
  { id: 'a1', version: 1, display_name: 'summary.pdf', media_type: 'application/pdf', size_bytes: 100, created_at: '2026-11-11T10:00:00.000Z' }], used_bytes: 1048576, quota_bytes: 2147483648 };

const reply = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
const calls: { method: string; url: string; body?: any; form?: FormData }[] = [];
function server(routes: Record<string, unknown> = {}, current: () => Catalogue = catalogue) {
  calls.length = 0;
  vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
    if (url === '/v1/csrf') return reply({ csrf_token: 't' });
    const method = init?.method ?? 'GET'; const form = init?.body instanceof FormData ? init.body : undefined;
    calls.push({ method, url, body: !form && init?.body ? JSON.parse(String(init.body)) : undefined, form });
    const found = routes[`${method} ${url}`];
    if (found !== undefined) return found instanceof Response ? Promise.resolve(found) : reply(found);
    if (url === '/v1/files') return reply(listing);
    if (url === '/v1/catalogue') return reply(current());
    return reply({});
  }));
}
const show = () => render(<MemoryRouter><Files /></MemoryRouter>);
const row = (name: string) => within(screen.getByText(name, { selector: '.file-card-text b' }).closest('.file-item') as HTMLElement);

describe('Files', () => {
  it('lists uploads and made files together, saying where each came from', async () => {
    server(); show();
    expect(await screen.findByText('summary.pdf')).toBeTruthy();
    expect(row('summary.pdf').getByText(/version 2 · Made by your assistant/)).toBeTruthy();
    expect(row('summary.pdf').getByRole('link', { name: 'Open the chat' }).getAttribute('href')).toBe('/chat/c1');
    expect(row('report.docx').getByText(/You uploaded it/)).toBeTruthy();
    expect(row('photo.png').getByText(/same content as “old photo.png”/)).toBeTruthy();
    expect(row('summary.pdf').getByRole('button', { name: /Download/ })).toBeTruthy();
    expect(screen.getByText(/^1\.0 MB of 2\.\d+ GB used$/)).toBeTruthy();
  });

  it('filters by where a file came from, its kind, its folder and its name', async () => {
    server(); show();
    await screen.findByText('summary.pdf');
    const names = () => [...document.querySelectorAll('.file-item .file-card-text b')].map(b => b.textContent);
    fireEvent.change(screen.getByLabelText('Where a file came from'), { target: { value: 'uploaded' } });
    expect(names()).toEqual(['report.docx', 'photo.png']);
    fireEvent.change(screen.getByLabelText('Kind of file'), { target: { value: 'picture' } });
    expect(names()).toEqual(['photo.png']);
    fireEvent.change(screen.getByLabelText('Kind of file'), { target: { value: '' } }); fireEvent.change(screen.getByLabelText('Where a file came from'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: /Reports 1/ }));
    expect(names()).toEqual(['photo.png']);
    fireEvent.click(screen.getByRole('button', { name: 'Not in a folder' }));
    expect(names()).toEqual(['summary.pdf', 'report.docx']);
    fireEvent.click(screen.getByRole('button', { name: 'All files' }));
    fireEvent.change(screen.getByLabelText('Search your files'), { target: { value: 'REPORT' } });
    expect(names()).toEqual(['report.docx']);
    fireEvent.change(screen.getByLabelText('Search your files'), { target: { value: 'nothing like this' } });
    expect(screen.getByText('No file matches “nothing like this”.')).toBeTruthy();
  });

  it('moves a file to a folder and renames it without touching the file', async () => {
    server(); show();
    await screen.findByText('report.docx');
    fireEvent.change(row('report.docx').getByLabelText('Folder of report.docx'), { target: { value: 'f1' } });
    await waitFor(() => expect(calls.find(c => c.url === '/v1/catalogue/place')?.body).toEqual({ kind: 'upload', id: 'u1', folder_id: 'f1' }));
    fireEvent.click(row('summary.pdf').getByRole('button', { name: 'Rename' }));
    fireEvent.change(screen.getByLabelText('New name for summary.pdf'), { target: { value: ' Board summary.pdf ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(calls.filter(c => c.url === '/v1/catalogue/place').at(-1)?.body).toEqual({ kind: 'made', id: 'a1', name: 'Board summary.pdf' }));
    fireEvent.change(row('photo.png').getByLabelText('Folder of photo.png'), { target: { value: '' } });
    await waitFor(() => expect(calls.filter(c => c.url === '/v1/catalogue/place').at(-1)?.body).toEqual({ kind: 'upload', id: 'u2', folder_id: null }));
  });

  it('makes a folder, and removing one says nothing inside is deleted', async () => {
    server({ 'POST /v1/folders': { folder: { id: 'f2' } }, 'POST /v1/folders/f1': { deleted: 'f1', files_moved_up: 1 } }); show();
    await screen.findByText('report.docx');
    fireEvent.click(screen.getByRole('button', { name: 'New folder' }));
    fireEvent.change(screen.getByLabelText('Name of the new folder'), { target: { value: 'Contracts' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(calls.find(c => c.url === '/v1/folders')?.body).toEqual({ project_id: 'p1', name: 'Contracts' }));
    fireEvent.click(screen.getByRole('button', { name: /Reports 1/ }));
    const remove = screen.getByRole('button', { name: 'Remove the folder “Reports”' });
    expect(remove.getAttribute('title')).toBe('What is inside moves up; nothing is deleted');
    fireEvent.click(remove);
    await waitFor(() => expect(calls.find(c => c.url === '/v1/folders/f1')?.body).toEqual({ delete: true }));
  });

  it('uploads into the open folder and says plainly what was linked or refused', async () => {
    server({ 'POST /v1/projects/p1/files': { result: { accepted: [{ id: 'n1', name: 'new.docx' }, { id: 'n2', name: 'twin.docx', same_as: 'u1' }], rejected: [{ name: 'macro.docx', reason: 'The file contains macros, which are not accepted' }] } } });
    show();
    await screen.findByText('report.docx');
    expect(screen.getByText(/Every file is checked before it is kept/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Reports 1/ }));
    const chosen = ['new.docx', 'twin.docx', 'macro.docx'].map(n => new File(['x'], n));
    fireEvent.change(screen.getByLabelText('Choose files to upload'), { target: { files: chosen } });
    expect(await screen.findByText('“macro.docx” was not kept: The file contains macros, which are not accepted.')).toBeTruthy();
    expect(screen.getByText('“twin.docx” has the same content as a file you already have. It was linked, not stored twice.')).toBeTruthy();
    const sent = calls.find(c => c.url === '/v1/projects/p1/files')!.form!;
    expect([sent.get('folder'), sent.getAll('file').length, sent.get('filenames')]).toEqual(['f1', 3, '["new.docx","twin.docx","macro.docx"]']);
  });

  it('deletes an upload and a made file through their own routes, after asking', async () => {
    server(); show();
    await screen.findByText('report.docx');
    fireEvent.click(row('report.docx').getByRole('button', { name: 'Delete report.docx' }));
    fireEvent.click(within(row('report.docx').getByRole('alertdialog')).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(calls.some(c => c.url === '/v1/uploads/u1/delete' && c.method === 'POST')).toBe(true));
    fireEvent.click(row('summary.pdf').getByRole('button', { name: 'Delete summary.pdf' }));
    expect(screen.getByText(/and its 2 versions/)).toBeTruthy();
    fireEvent.click(within(row('summary.pdf').getByRole('alertdialog')).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(calls.some(c => c.url === '/v1/artifacts/a1/delete')).toBe(true));
  });

  it('offers no upload where uploads are off, and says so when there is nothing yet', async () => {
    server({}, () => catalogue({ files: [], folders: [], total: 0, uploads: false })); show();
    expect(await screen.findByText(/Nothing yet\. Ask Lumina for a file/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Upload/ })).toBeNull();
    expect(screen.queryByText(/You can also upload your own/)).toBeNull();
  });
});
