import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { FrameProvider } from './FrameProvider';
import Workspace from './Workspace';
import { Table } from './parts';

const at = (px: number) => { Object.defineProperty(window, 'innerWidth', { configurable: true, value: px }); };
const page = (extra: Partial<Parameters<typeof Workspace>[0]> = {}) => render(<MemoryRouter><FrameProvider person="a@example.com">
  <Workspace title="Place" context={<button>In the context</button>} contextLabel="Folders" inspector={<p>Open thing</p>} inspectorLabel="Details" onInspectorClose={() => undefined} {...extra}>
    <button>In the canvas</button>
  </Workspace></FrameProvider></MemoryRouter>);

beforeEach(() => { localStorage.clear(); });
afterEach(() => { cleanup(); at(1024); });

describe('Workspace in the frame', () => {
  it('docks the context and the inspector beside the canvas at 1280 px, with the title in the canvas toolbar', () => {
    at(1280); page();
    expect(screen.getByRole('heading', { level: 1, name: 'Place' })).toBeTruthy();
    expect(within(screen.getByRole('complementary', { name: 'Folders' })).getByText('In the context')).toBeTruthy();
    expect(within(screen.getByRole('complementary', { name: 'Details' })).getByText('Open thing')).toBeTruthy();
    expect(screen.getByRole('main')).toBeTruthy();
    expect(screen.getAllByRole('separator')).toHaveLength(2);
  });

  it('at 820 px opens the inspector as a sheet that closes with Escape', () => {
    at(820); let closed = 0;
    page({ onInspectorClose: () => { closed++; } });
    expect(screen.queryByRole('complementary', { name: 'Details' })).toBeNull();
    const sheet = screen.getByRole('dialog', { name: 'Details' });
    fireEvent.keyDown(sheet, { key: 'Escape' });
    expect(closed).toBe(1);
  });

  it('on a phone shows one zone at a time: the context opens as a sheet from the toolbar and returns focus when it closes', () => {
    at(390); page({ inspector: null });
    expect(screen.queryByRole('complementary', { name: 'Folders' })).toBeNull();
    const toggle = screen.getByRole('button', { name: 'Show folders' }); toggle.focus();
    fireEvent.click(toggle);
    const sheet = screen.getByRole('dialog', { name: 'Folders' });
    expect(within(sheet).getByText('In the context')).toBeTruthy();
    fireEvent.keyDown(sheet, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Show folders' }));
  });

  it('folds the context column away and remembers it', () => {
    at(1280); page();
    fireEvent.click(screen.getByRole('button', { name: 'Hide folders' }));
    expect(screen.queryByRole('complementary', { name: 'Folders' })).toBeNull();
    cleanup(); page();
    expect(screen.queryByRole('complementary', { name: 'Folders' })).toBeNull();
    expect(screen.getByRole('button', { name: 'Show folders' })).toBeTruthy();
  });

  it('resizes a zone from the keyboard (arrows, Home, End) and remembers the width', () => {
    at(1280); page();
    const edge = screen.getByRole('separator', { name: 'Resize the side column' });
    const before = Number(edge.getAttribute('aria-valuenow'));
    fireEvent.keyDown(edge, { key: 'ArrowRight' });
    expect(Number(screen.getByRole('separator', { name: 'Resize the side column' }).getAttribute('aria-valuenow'))).toBe(before + 24);
    fireEvent.keyDown(edge, { key: 'Home' });
    expect(screen.getByRole('separator', { name: 'Resize the side column' }).getAttribute('aria-valuenow')).toBe('200');
    cleanup(); page();
    expect(screen.getByRole('separator', { name: 'Resize the side column' }).getAttribute('aria-valuenow')).toBe('200');
  });

  it('offers Narrower and Wider in the zone menu, the way to resize without dragging', async () => {
    at(1280); page();
    fireEvent.click(screen.getByRole('button', { name: 'Folders options' }));
    await act(async () => { fireEvent.click(await screen.findByRole('menuitem', { name: 'Wider' })); });
    expect(Number(screen.getByRole('separator', { name: 'Resize the side column' }).getAttribute('aria-valuenow'))).toBe(248 + 72);
  });

  it('shows every zone in place where there is no frame (tests, the gallery)', () => {
    render(<MemoryRouter><Workspace title="Plain" context={<p>c</p>} inspector={<p>i</p>}><p>canvas</p></Workspace></MemoryRouter>);
    expect(screen.getByText('c')).toBeTruthy(); expect(screen.getByText('i')).toBeTruthy(); expect(screen.getByText('canvas')).toBeTruthy();
  });
});

describe('Table', () => {
  const rows = [{ id: 'a', name: 'Beta', n: 2 }, { id: 'b', name: 'Alpha', n: 9 }];
  it('sorts by a column heading and opens a row with Enter', () => {
    let opened = '';
    render(<Table label="Things" rows={rows} rowKey={r => r.id} onOpen={r => { opened = r.id; }} columns={[{ key: 'name', label: 'Name', render: r => r.name, sort: r => r.name }, { key: 'n', label: 'Count', render: r => String(r.n) }]} />);
    fireEvent.click(screen.getByRole('button', { name: 'Name' }));
    expect(screen.getAllByRole('row').slice(1).map(r => r.textContent)).toEqual(['Beta2', 'Alpha9']);
    fireEvent.click(screen.getByRole('button', { name: 'Name' }));
    expect(screen.getAllByRole('row').slice(1).map(r => r.textContent)).toEqual(['Alpha9', 'Beta2']);
    expect(screen.getByRole('columnheader', { name: 'Name' }).getAttribute('aria-sort')).toBe('ascending');
    fireEvent.keyDown(screen.getAllByRole('row')[1], { key: 'Enter' });
    expect(opened).toBe('b');
  });
});
