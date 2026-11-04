import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { Settings } from './Settings';
import { api } from '../lib/api';
vi.mock('../lib/api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
vi.mock('../state/data', () => ({ useData: () => ({ app: { user: { email: 'me@example.com' }, features: { billing_mode: 'open' } }, signOut: vi.fn() }) }));
vi.mock('../state/settings', () => ({ useSettings: () => ({ reducedMotion: false, compact: false, setReducedMotion: vi.fn(), setCompact: vi.fn() }) }));
vi.mock('../components/YourBrowser', () => ({ default: () => <p>Your browser card</p> }));
vi.mock('../components/OwnModel', () => ({ default: () => <p>Own model card</p> }));
vi.mock('../components/MemoryNotes', () => ({ default: () => <p>Memory card</p> }));
vi.mock('../components/Credits', () => ({ default: () => <p>Credits card</p> }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
describe('Settings', () => {
  it('shows only one section at a time, starting with General', () => {
    vi.mocked(api).mockResolvedValue({} as any);
    render(<Settings />);
    expect(screen.getByRole('tab', { name: 'General', selected: true })).toBeTruthy();
    expect(screen.getByText('Reduce motion')).toBeTruthy();
    expect(screen.queryByText('Your browser card')).toBeNull();
  });
  it('switches sections by click and by arrow keys', () => {
    vi.mocked(api).mockResolvedValue({} as any);
    render(<Settings />);
    fireEvent.click(screen.getByRole('tab', { name: 'Assistant' }));
    expect(screen.getByText('Your browser card')).toBeTruthy(); expect(screen.getByText('Memory card')).toBeTruthy();
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Assistant' }), { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: 'Usage', selected: true })).toBeTruthy();
  });
  it('shows what is left of the allowance and what was used, and says so honestly when usage is unavailable', async () => {
    vi.mocked(api).mockResolvedValue({ reported_microusd: 400000, held_microusd: 100000, period_remaining_microusd: 1500000, period_limit_microusd: 2000000 } as any);
    render(<Settings />); fireEvent.click(screen.getByRole('tab', { name: 'Usage' }));
    expect(await screen.findByText('$1.50')).toBeTruthy(); expect(screen.getByText('$0.40')).toBeTruthy();
    expect(screen.getByRole('img', { name: "25% of this period's allowance used" })).toBeTruthy();
    cleanup(); vi.mocked(api).mockRejectedValue(new Error('x'));
    render(<Settings />); fireEvent.click(screen.getByRole('tab', { name: 'Usage' }));
    expect(await screen.findByText('Usage is not available right now.')).toBeTruthy();
  });
  it('shows the signed-in email on the Account tab', () => {
    vi.mocked(api).mockResolvedValue({} as any);
    render(<Settings />); fireEvent.click(screen.getByRole('tab', { name: 'Account' }));
    expect(screen.getByText('me@example.com')).toBeTruthy(); expect(screen.getByRole('button', { name: 'Sign out' })).toBeTruthy();
  });
});
