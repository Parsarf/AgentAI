import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Home from './Home';
import { TEMPLATES } from '../components/Composer';

vi.mock('../state/data', () => ({ useData: () => ({
  app: { user: { email: 'design-test@example.com' }, features: { execution: true }, limits: { max_message_chars: 16000 } },
  requests: [], refresh: vi.fn(),
}) }));
afterEach(() => { cleanup(); localStorage.clear(); });

it('keeps every capability keyboard reachable and seeds the composer without duplicating controls', () => {
  render(<MemoryRouter><Home /></MemoryRouter>);
  expect(screen.getByRole('group', { name: 'How should Lumina respond' })).toBeTruthy();
  expect(screen.queryByRole('button', { name: /^Web$/ })).toBeNull();
  for (const [name, key] of [['Search Web', 'Web'], ['Build & Code', 'Code'], ['Analyze Data', 'Data'], ['Automate', 'Automate']]) {
    fireEvent.click(screen.getByRole('button', { name: new RegExp(name) }));
    expect((screen.getByRole('textbox', { name: 'Message Lumina' }) as HTMLTextAreaElement).value).toBe(TEMPLATES[key]);
  }
});
