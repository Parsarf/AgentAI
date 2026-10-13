import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ChatList from './ChatList';
import type { ChatSummary } from '../lib/chats';

const now = new Date(); const iso = (d: Date) => d.toISOString();
const chats: ChatSummary[] = [
  { id: 'a', project_id: 'p', created_at: iso(now), title: 'Pickleball rackets', last_activity: iso(now), active: 1 },
  { id: 'b', project_id: 'p', created_at: '2026-01-01T00:00:00Z', title: null, last_activity: null, active: 0 }];
afterEach(cleanup);

describe('ChatList', () => {
  it('groups chats by day, marks the open chat and shows a working indicator', () => {
    render(<MemoryRouter><ChatList chats={chats} current="a" /></MemoryRouter>);
    expect(screen.getByText('Today')).toBeTruthy(); expect(screen.getByText('Earlier')).toBeTruthy();
    expect(screen.getByRole('link', { name: /Pickleball rackets/ }).getAttribute('aria-current')).toBe('page');
    expect(screen.getByTitle('Working')).toBeTruthy(); expect(screen.getByRole('link', { name: 'New chat' }).getAttribute('href')).toBe('/chat/b');
  });
  it('says so when there are no chats', () => {
    render(<MemoryRouter><ChatList chats={[]} /></MemoryRouter>);
    expect(screen.getByText(/chats will appear here/i)).toBeTruthy();
  });
});
