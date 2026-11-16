import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Settings } from './Settings';
import { api } from '../lib/api';
vi.mock('../lib/api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
vi.mock('../state/data', () => ({ useData: () => ({ app: { user: { email: 'me@example.com' }, features: { billing_mode: 'open' } }, signOut: vi.fn() }) }));
const setContrast = vi.fn();
vi.mock('../state/settings', () => ({ useSettings: () => ({ reducedMotion: false, compact: false, contrast: 'system', setReducedMotion: vi.fn(), setCompact: vi.fn(), setContrast }) }));
vi.mock('./Info', () => ({ Integrations: () => <p>Integrations section</p> }));
vi.mock('../components/YourBrowser', () => ({ default: () => <p>Your browser card</p> }));
vi.mock('../components/OwnModel', () => ({ default: () => <p>Own model card</p> }));
vi.mock('../components/MemoryNotes', () => ({ default: () => <p>Memory card</p> }));
vi.mock('../components/Credits', () => ({ default: () => <p>Credits card</p> }));
vi.mock('../components/SpendingLimits', () => ({ default: () => <p>Spending limits card</p> }));
vi.mock('../components/AccessPage', () => ({ default: () => <p>Access page</p> }));
vi.mock('../components/DataControls', () => ({ default: () => <p>Data controls</p> }));
vi.mock('../components/Organization', () => ({ default: () => <p>Organization card</p> }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
// UI remodel phase 6: Settings sits in the frame, its sections in the context column with an address each (/settings/<section>); Integrations is one of them.
const show = (path = '/settings') => render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/settings/:section?" element={<Settings />} /></Routes></MemoryRouter>);
describe('Settings', () => {
  it('shows only one section at a time, starting with General', () => {
    vi.mocked(api).mockResolvedValue({} as any);
    show();
    expect(screen.getByRole('tab', { name: 'General', selected: true })).toBeTruthy();
    expect(screen.getByText('Reduce motion')).toBeTruthy();
    expect(screen.queryByText('Your browser card')).toBeNull();
  });
  it('switches sections by click and by arrow keys', () => {
    vi.mocked(api).mockResolvedValue({} as any);
    show();
    fireEvent.click(screen.getByRole('tab', { name: 'Assistant' }));
    expect(screen.getByText('Your browser card')).toBeTruthy(); expect(screen.getByText('Memory card')).toBeTruthy();
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Assistant' }), { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: 'Access', selected: true })).toBeTruthy(); expect(screen.getByText('Access page')).toBeTruthy();
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Access' }), { key: 'ArrowDown' });            // a vertical list in the side column: up and down too
    expect(screen.getByRole('tab', { name: 'Integrations', selected: true })).toBeTruthy();
    fireEvent.keyDown(screen.getByRole('tab', { name: 'Integrations' }), { key: 'ArrowRight' });
    expect(screen.getByRole('tab', { name: 'Usage', selected: true })).toBeTruthy();
    fireEvent.click(screen.getByRole('tab', { name: 'Account' }));
    expect(screen.getByText('Organization card')).toBeTruthy(); expect(screen.getByText('Data controls')).toBeTruthy();
  });
  it('shows what was used with no limit by default, next to the card where a limit can be set', async () => {
    vi.mocked(api).mockResolvedValue({ reported_microusd: 400000, held_microusd: 0, day_reported_microusd: 150000, period_remaining_microusd: null, period_limit_microusd: null } as any);
    show(); fireEvent.click(screen.getByRole('tab', { name: 'Usage' }));
    expect(await screen.findByText(/used · no spending limit/)).toBeTruthy();
    expect(screen.getAllByText('$0.40').length).toBeGreaterThan(0); expect(screen.getByText('$0.15')).toBeTruthy();
    expect(screen.queryByRole('img')).toBeNull();                                                  // no meter: there is nothing to measure against
    expect(screen.getByText('Spending limits card')).toBeTruthy();
  });
  it('shows what is left of the limit the customer set and what was used, and says so honestly when usage is unavailable', async () => {
    vi.mocked(api).mockResolvedValue({ reported_microusd: 400000, held_microusd: 100000, period_remaining_microusd: 1500000, period_limit_microusd: 2000000 } as any);
    show(); fireEvent.click(screen.getByRole('tab', { name: 'Usage' }));
    expect(await screen.findByText('$1.50')).toBeTruthy(); expect(screen.getByText('$0.40')).toBeTruthy();
    expect(screen.getByRole('img', { name: '25% of your limit for this period used' })).toBeTruthy();
    cleanup(); vi.mocked(api).mockRejectedValue(new Error('x'));
    show(); fireEvent.click(screen.getByRole('tab', { name: 'Usage' }));
    expect(await screen.findByText('Usage is not available right now.')).toBeTruthy();
  });
  it('opens a section from its address, from the older ?tab= form, and offers Integrations as a section', () => {
    vi.mocked(api).mockResolvedValue({} as any);
    show('/settings/integrations'); expect(screen.getByText('Integrations section')).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'Integrations', selected: true })).toBeTruthy();
    cleanup(); show('/settings/memory'); expect(screen.getByText('Memory card')).toBeTruthy();                  // an older name lands on the section that holds it
  });
  it('offers more contrast, or following the device', () => {
    vi.mocked(api).mockResolvedValue({} as any);
    show(); expect(screen.getByRole('radio', { name: 'Like this device', checked: true })).toBeTruthy();
    fireEvent.click(screen.getByRole('radio', { name: 'More contrast' }));
    expect(setContrast).toHaveBeenCalledWith('more');
  });
  it('shows the signed-in email on the Account tab', () => {
    vi.mocked(api).mockResolvedValue({} as any);
    show(); fireEvent.click(screen.getByRole('tab', { name: 'Account' }));
    expect(screen.getByText('me@example.com')).toBeTruthy(); expect(screen.getByRole('button', { name: 'Sign out' })).toBeTruthy();
  });
});
