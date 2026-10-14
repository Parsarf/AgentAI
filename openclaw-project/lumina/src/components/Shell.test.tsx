import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Shell from './Shell';
vi.mock('../state/data', () => ({ useData: () => ({ requests: [], chats: [], refreshChats: vi.fn() }) }));
vi.mock('../state/settings', () => ({ useSettings: () => ({ sidebarOpen: true, reducedMotion: false, setReducedMotion: vi.fn(), setSidebarOpen: vi.fn() }) }));
vi.mock('./Sidebar', () => ({ default: () => null }));
vi.mock('./Backdrop', () => ({ default: () => <div data-testid="backdrop" /> }));
afterEach(cleanup);
describe('conversation background', () => {
  it('hides decorative scenery in an active conversation', () => {
    render(<MemoryRouter initialEntries={['/chat/example']}><Shell /></MemoryRouter>);
    expect(screen.queryByTestId('backdrop')).toBeNull();
  });
  it.each(['/chat', '/home'])('retains scenery on %s', path => {
    render(<MemoryRouter initialEntries={[path]}><Shell /></MemoryRouter>);
    expect(screen.getByTestId('backdrop')).toBeTruthy();
  });
});
