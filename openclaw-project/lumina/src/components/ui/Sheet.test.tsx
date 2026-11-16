import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, describe, expect, it } from 'vitest';
import Sheet from './Sheet';

afterEach(cleanup);
function Harness() {
  const [open, setOpen] = useState(false);
  return <><button onClick={() => setOpen(true)}>Open</button>{open && <Sheet title="Things" onClose={() => setOpen(false)}><button>First</button><button>Last</button></Sheet>}</>;
}

describe('Sheet', () => {
  it('moves focus inside, keeps Tab inside, closes with Escape and gives focus back to what opened it', () => {
    render(<Harness />);
    const opener = screen.getByRole('button', { name: 'Open' }); opener.focus(); fireEvent.click(opener);
    const dialog = screen.getByRole('dialog', { name: 'Things' });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'First' }));
    screen.getByRole('button', { name: 'Last' }).focus();
    fireEvent.keyDown(dialog, { key: 'Tab' });
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'Close' }));
    fireEvent.keyDown(dialog, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(opener);
  });

  it('closes from the scrim but not from a click inside', () => {
    render(<Harness />); fireEvent.click(screen.getByRole('button', { name: 'Open' }));
    fireEvent.mouseDown(screen.getByRole('button', { name: 'First' }));
    expect(screen.getByRole('dialog')).toBeTruthy();
    fireEvent.mouseDown(document.querySelector('.sheet-scrim')!);
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
