import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import Menu from './Menu';
import Toggle from './Toggle';
afterEach(cleanup);
const setup = (onSelect = vi.fn()) => render(
  <Menu label="Tools" heading="Tools" checkable items={[{ id: 'a', label: 'Web search', checked: true, onSelect }, { id: 'b', label: 'Run code', onSelect: vi.fn() }, { id: 'c', label: 'Locked', disabled: true, onSelect: vi.fn() }]}
    trigger={({ open, props }) => <button aria-expanded={open} {...props}>Open tools</button>} />);
describe('Menu', () => {
  it('opens as a menu, marks the chosen row and focuses it', () => {
    setup(); fireEvent.click(screen.getByRole('button', { name: 'Open tools' }));
    expect(screen.getByRole('menu', { name: 'Tools' })).toBeTruthy();
    const checked = screen.getByRole('menuitemradio', { name: 'Web search' });
    expect(checked.getAttribute('aria-checked')).toBe('true'); expect(document.activeElement).toBe(checked);
  });
  it('moves with the arrow keys, skips disabled rows and wraps', () => {
    setup(); fireEvent.click(screen.getByRole('button', { name: 'Open tools' }));
    const menu = screen.getByRole('menu'); fireEvent.keyDown(menu, { key: 'ArrowDown' });
    expect(document.activeElement).toBe(screen.getByRole('menuitemradio', { name: 'Run code' }));
    fireEvent.keyDown(menu, { key: 'ArrowDown' }); expect(document.activeElement).toBe(screen.getByRole('menuitemradio', { name: 'Web search' }));
  });
  it('closes on Escape and gives focus back to the trigger', () => {
    setup(); const trigger = screen.getByRole('button', { name: 'Open tools' }); fireEvent.click(trigger);
    fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull(); expect(document.activeElement).toBe(trigger);
  });
  it('runs the chosen action once and closes', () => {
    const onSelect = vi.fn(); setup(onSelect); fireEvent.click(screen.getByRole('button', { name: 'Open tools' }));
    fireEvent.click(screen.getByRole('menuitemradio', { name: 'Web search' })); expect(onSelect).toHaveBeenCalledTimes(1); expect(screen.queryByRole('menu')).toBeNull();
  });
  it('closes when the pointer goes down outside', () => {
    setup(); fireEvent.click(screen.getByRole('button', { name: 'Open tools' })); fireEvent.mouseDown(document.body); expect(screen.queryByRole('menu')).toBeNull();
  });
});
describe('Toggle', () => {
  it('is a labelled switch that reports its state', () => {
    const onChange = vi.fn(); render(<Toggle label="Compact layout" checked={false} onChange={onChange} />);
    const sw = screen.getByRole('switch', { name: 'Compact layout' }); expect(sw.getAttribute('aria-checked')).toBe('false');
    fireEvent.click(sw); expect(onChange).toHaveBeenCalledWith(true);
  });
});
