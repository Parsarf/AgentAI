import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import DocumentView, { type DocumentData } from './DocumentView';

let features: Record<string, boolean> = { knowledge: true, convert: true };
vi.mock('../state/data', () => ({ useData: () => ({ app: { features } }) }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); features = { knowledge: true, convert: true }; });

const doc: DocumentData = {
  source: { id: 's1', kind: 'upload', name: 'contract.pdf', media_type: 'application/pdf', size_bytes: 1, state: 'ready', step: null, error: null, pages: 2, passages: 3, tables: 1, charts: 1,
    read_by_model: 1, low_confidence: true, unread_pages: 0, parser: 'p', scope: 'account', origin: null, added_epoch: 1, updated_epoch: 1, indexed_epoch: 1, own: true },
  title: 'Contract', pages: 2, format: 'pdf', notes: [],
  blocks: [{ id: 'b1', kind: 'heading', text: 'Payment', page: 1, level: 1 }, { id: 'b2', kind: 'paragraph', text: 'The fee is 4,000 EUR a month.', page: 1 },
    { id: 'b3', kind: 'table', text: '', page: 2, rows: [['Item', 'Amount'], ['Fee', '4000']], header_rows: 1, title: 'Fees' },
    { id: 'b4', kind: 'paragraph', text: 'Signed in Lisbon', page: 2, source: 'vision', confidence: 0.4 },
    { id: 'b5', kind: 'chart', text: '', page: 2, title: 'Sales', series: [{ name: '2026', points: [{ label: 'Q1', value: '10', basis: 'printed' }, { label: 'Q2', value: '12', basis: 'estimated' }] }] }],
  passages: [{ id: 'p1', page: 1, blocks: ['b1', 'b2'], section: 'Payment' }, { id: 'p2', page: 2, blocks: ['b3'], section: null }],
};
const show = (at: string, answer: unknown = doc, status = 200) => {
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response(JSON.stringify(answer), { status, headers: { 'Content-Type': 'application/json' } }))));
  return render(<MemoryRouter initialEntries={[at]}><Routes><Route path="/knowledge/:sourceId" element={<DocumentView />} /></Routes></MemoryRouter>);
};

describe('DocumentView', () => {
  it('opens at the cited passage and marks it, page by page', async () => {
    show('/knowledge/s1?passage=p1');
    expect(await screen.findByText('The fee is 4,000 EUR a month.')).toBeTruthy();
    const cited = document.querySelectorAll('.doc-block.cited');
    expect([...cited].map(b => b.getAttribute('data-block'))).toEqual(['b1', 'b2']);
    expect(screen.getByRole('region', { name: 'Page 2' })).toBeTruthy();
  });
  it('says where text was read from a picture, shows tables with an export and keeps estimated chart values apart', async () => {
    show('/knowledge/s1');
    expect(await screen.findByText(/may contain errors/)).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Download as Excel' })).toBeTruthy();
    expect(screen.getByText(/estimated from the picture/)).toBeTruthy();
    expect(screen.getAllByText('estimated')).toHaveLength(1);
    expect(document.querySelectorAll('.doc-block.cited')).toHaveLength(0);
  });
  it('says so when the document is not there or not theirs', async () => {
    show('/knowledge/zz', { error: 'not_found' }, 404);
    expect(await screen.findByText(/not there, or you may not read it/)).toBeTruthy();
  });
});
