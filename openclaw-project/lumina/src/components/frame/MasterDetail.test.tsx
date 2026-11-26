import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import MasterDetail from './MasterDetail';

afterEach(cleanup);

describe('MasterDetail', () => {
  it('keeps the list mounted while something is open, so it keeps its place', () => {
    const { rerender } = render(<MasterDetail listLabel="Conversations" detailLabel="Open conversation" open={false} list={<p>the list</p>} detail={<p>the open one</p>} empty={<p>nothing open</p>} />);
    expect(screen.getByRole('region', { name: 'Conversations' }).textContent).toBe('the list');
    expect(screen.getByRole('region', { name: 'Open conversation' }).textContent).toBe('nothing open');
    expect(document.querySelector('.master-detail')!.className).not.toContain('md-open');
    const list = screen.getByText('the list');
    rerender(<MasterDetail listLabel="Conversations" detailLabel="Open conversation" open list={<p>the list</p>} detail={<p>the open one</p>} empty={<p>nothing open</p>} />);
    expect(screen.getByText('the list')).toBe(list);                                              // the same element: not drawn again
    expect(screen.getByRole('region', { name: 'Open conversation' }).textContent).toBe('the open one');
    expect(document.querySelector('.master-detail')!.className).toContain('md-open');                        // which one a narrow canvas shows is the stylesheet's decision, from this
  });
});
