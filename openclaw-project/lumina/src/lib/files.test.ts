import { describe, expect, it } from 'vitest';
import { extension, fileKind, groupFiles, humanSize, previewAs, splitPath, tableData, toCsv } from './files';

const row = (id: string, version: number, name: string, at: string) => ({ id, version, display_name: name, media_type: 'text/plain', size_bytes: 10, created_at: at });
describe('files', () => {
  it('keeps the newest version per file, newest file first, hides bundles', () => {
    const g = groupFiles([row('a', 1, 'a.py', '2026-10-13 10:00:00'), row('a', 2, 'a.py', '2026-10-13 11:00:00'), row('b', 1, 'b.md', '2026-10-13 12:00:00'), row('z', 1, 'project-x-bundle.zip', '2026-10-13 13:00:00')]);
    expect(g.map(x => [x.name, x.latest.version, x.versions])).toEqual([['b.md', 1, 1], ['a.py', 2, 2]]);
    expect(g[1].all.map(v => v.version)).toEqual([2, 1]);
  });
  it('treats the same name in two chats as two files', () => {
    const g = groupFiles([row('a', 1, 'report.pdf', '2026-10-13 10:00:00'), row('b', 1, 'report.pdf', '2026-10-13 11:00:00')]);
    expect(g.map(x => x.id)).toEqual(['b', 'a']);
  });
  it('formats sizes', () => { expect(humanSize(5)).toBe('5 B'); expect(humanSize(2048)).toBe('2.0 KB'); expect(humanSize(5 * 1048576)).toBe('5.0 MB'); expect(humanSize(2 * 1073741824)).toBe('2.00 GB'); });
  it('reads folder, ending and kind from a name', () => {
    expect(splitPath('reports/2026/Q3 sales.xlsx')).toEqual({ folder: 'reports/2026', name: 'Q3 sales.xlsx' });
    expect(splitPath('notes.md')).toEqual({ folder: '', name: 'notes.md' });
    expect([extension('a/b.c/Deck.PPTX'), extension('noext'), extension('.env')]).toEqual(['pptx', '', '']);
    expect(['x.pdf', 'x.docx', 'x.xlsx', 'x.pptx', 'x.png', 'x.zip', 'x.weird'].map(fileKind)).toEqual(['pdf', 'doc', 'sheet', 'slides', 'image', 'archive', 'other']);
  });
  it('knows what can be looked at before downloading', () => {
    expect(['a.pdf', 'a.docx', 'a.xlsx', 'a.pptx', 'a.png'].map(previewAs)).toEqual(['picture', 'picture', 'picture', 'picture', 'picture']);
    expect(['a.md', 'a.csv', 'a.json', 'a.svg', 'a.html'].map(previewAs)).toEqual(['text', 'text', 'text', 'text', 'text']);   // markup is shown as source, never rendered
    expect(['a.zip', 'a.mp4', 'a.epub', 'a.tiff', 'a.bin'].map(previewAs)).toEqual([null, null, null, null, null]);
  });
  it('turns a table into data and CSV, keeping formula-looking text as text', () => {
    const table = document.createElement('table');
    table.innerHTML = '<thead><tr><th>Item</th><th>Price</th><th>Code</th></tr></thead><tbody><tr><td>Tea, green</td><td>3.50</td><td>007</td></tr><tr><td>=SUM(A1)</td><td>-2</td><td>say "hi"</td></tr></tbody>';
    const data = tableData(table);
    expect(data).toEqual({ columns: ['Item', 'Price', 'Code'], rows: [['Tea, green', 3.5, '007'], ['=SUM(A1)', -2, 'say "hi"']] });
    expect(toCsv(data.columns, data.rows)).toBe('Item,Price,Code\r\n"Tea, green",3.5,007\r\n\'=SUM(A1),-2,"say ""hi"""\r\n');
  });
});
