import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import WorkTrail from './WorkTrail';
import type { Message } from '../../lib/conversations';

const msgs = [{ id: 1, request_id: 'r', provenance: 'agent', content: 'Let me look that up', created_at: '' }, { id: 2, request_id: 'r', provenance: 'agent', content: 'Found it', created_at: '' }] as Message[];
afterEach(cleanup);

describe('the folded steps', () => {
  it('starts closed with a button that says how many steps there are', () => {
    render(<WorkTrail messages={msgs} />);
    const button = screen.getByRole('button', { name: 'Show the steps (2)' });
    expect(button.getAttribute('aria-expanded')).toBe('false');
    expect(screen.queryByText('Let me look that up')).toBeNull();
  });
  it('opens and closes', () => {
    render(<WorkTrail messages={msgs} />);
    fireEvent.click(screen.getByRole('button', { name: /Show the steps/ }));
    expect(screen.getByText('Let me look that up')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Hide the steps' }));
    expect(screen.queryByText('Let me look that up')).toBeNull();
  });
});
