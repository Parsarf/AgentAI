import { describe, expect, it } from 'vitest';
import { groupFiles, humanSize } from './files';

const row = (id: string, version: number, name: string, at: string) => ({ id, version, display_name: name, media_type: 'text/plain', size_bytes: 10, created_at: at });
describe('files', () => {
  it('keeps the newest version per name, newest file first, hides bundles', () => {
    const g = groupFiles([row('a', 1, 'a.py', '2026-10-13 10:00:00'), row('a', 2, 'a.py', '2026-10-13 11:00:00'), row('b', 1, 'b.md', '2026-10-13 12:00:00'), row('z', 1, 'project-x-bundle.zip', '2026-10-13 13:00:00')]);
    expect(g.map(x => [x.name, x.latest.version, x.versions])).toEqual([['b.md', 1, 1], ['a.py', 2, 2]]);
  });
  it('formats sizes', () => { expect(humanSize(5)).toBe('5 B'); expect(humanSize(2048)).toBe('2.0 KB'); expect(humanSize(5 * 1048576)).toBe('5.0 MB'); });
});
