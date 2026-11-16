import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import List from './List';

afterEach(cleanup);
const items = Array.from({ length: 100000 }, (_, i) => ({ id: `t${i}`, text: `Row ${i}` }));
const box = (el: Element, height: number) => Object.defineProperty(el, 'clientHeight', { configurable: true, value: height });

describe('virtualized List', () => {
  it('renders a screenful of 100,000 rows, not all of them, and tells screen readers the size and position', () => {
    render(<List label="Rows" items={items} rowHeight={50} rowKey={i => i.id} renderRow={i => <span>{i.text}</span>} />);
    const rows = screen.getAllByRole('listitem');
    expect(rows.length).toBeLessThan(60);
    expect(rows[0].getAttribute('aria-setsize')).toBe('100000');
    expect(rows[0].getAttribute('aria-posinset')).toBe('1');
    expect(screen.getByRole('list', { name: 'Rows' }).style.height).toBe('5000000px');
  });

  it('renders the rows in view after a scroll', () => {
    const { container } = render(<List label="Rows" items={items} rowHeight={50} rowKey={i => i.id} renderRow={i => <span>{i.text}</span>} />);
    const scroller = container.querySelector('.vlist')!; box(scroller, 500);
    scroller.scrollTop = 50 * 70000; fireEvent.scroll(scroller);
    expect(screen.getByText('Row 70000')).toBeTruthy();
    expect(screen.queryByText('Row 0')).toBeNull();
  });

  it('asks for more near the end, once per length', () => {
    const more = vi.fn();
    const few = items.slice(0, 20);
    const { rerender } = render(<List label="Rows" items={few} rowHeight={50} rowKey={i => i.id} renderRow={i => i.text} onEnd={more} />);
    expect(more).toHaveBeenCalledTimes(1);
    rerender(<List label="Rows" items={few} rowHeight={50} rowKey={i => i.id} renderRow={i => i.text} onEnd={more} />);
    expect(more).toHaveBeenCalledTimes(1);
  });

  it('scrolls the keyboard\'s row into view', () => {
    const { container, rerender } = render(<List label="Rows" items={items} rowHeight={50} rowKey={i => i.id} renderRow={i => i.text} active={0} />);
    const scroller = container.querySelector('.vlist')!; box(scroller, 500);
    rerender(<List label="Rows" items={items} rowHeight={50} rowKey={i => i.id} renderRow={i => i.text} active={40} />);
    expect(scroller.scrollTop).toBe(41 * 50 - 500);
  });
});
