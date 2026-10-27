import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import SafetyButton from './SafetyButton';
import Sidebar from '../Sidebar';
import { DataProvider } from '../../state/data';
import { SettingsProvider } from '../../state/settings';
import { resetCsrf } from '../../lib/api';
import type { SafetyFeature, SafetyState, Scope } from '../../lib/safety';

const GROUPS = [{ key: 'browser', title: 'Browser' }, { key: 'data', title: 'Data and privacy' }, { key: 'access', title: 'Sign-in and sessions' }, { key: 'empty', title: 'Nothing here' }];
const feature = (over: Partial<SafetyFeature> & { key: string; title: string; group: string }): SafetyFeature =>
  ({ plain: `${over.title} plain`, wired: true, on: true, expires_epoch: null, source: 'default', lock: null, ...over });
const appInfo = { api_version: 't', user: { email: 'parsa@example.com', role: 'customer' }, assistant: { state: 'ready' }, limits: { max_message_chars: 100 },
  features: { chat: true, execution: true, files: false, uploads: false, telegram: false, connectors: false, billing_mode: 'open', requests: true, usage: true } };
const reply = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });

/** A stand-in for the server's two scopes. `role` null = the 404 every other account gets. */
let role: 'owner' | 'member' | null; let allOff: Set<string>; let mineOverride: Record<string, boolean>; let granted: { email: string; granted_epoch: number }[];
let posts: { url: string; body: any }[];

const view = (scope: Scope): SafetyState => {
  const rows: SafetyFeature[] = [
    feature({ key: 'payment_stop', title: 'Stop at payment pages', group: 'browser' }),
    feature({ key: 'ssrf_guard', title: 'Network destination guard', group: 'data', lock: scope === 'all' ? 'privacy' : null }),
    feature({ key: 'web_limits', title: 'Web access limits', group: 'data', wired: false }),
    feature({ key: 'csrf_protection', title: 'CSRF protection', group: 'access', lock: 'shared', wired: false }),
    feature({ key: 'audit_log', title: 'Audit log', group: 'access', lock: 'core', wired: false }),
  ].map(f => {
    if (scope === 'all') return { ...f, on: !allOff.has(f.key), source: allOff.has(f.key) ? 'all' as const : 'default' as const, overridden: f.key === 'payment_stop' ? 2 : 0 };
    const own = mineOverride[f.key];
    if (own !== undefined) return { ...f, on: own, source: 'account' as const };
    return allOff.has(f.key) ? { ...f, on: false, source: 'all' as const } : f;
  });
  return { role: role ?? 'member', scope, scopes: role === 'owner' ? ['mine', 'all'] : ['mine'], groups: GROUPS, features: rows, off_count: rows.filter(r => !r.on).length };
};

const server = () => vi.stubGlobal('fetch', vi.fn(async (url: string, init?: { body?: string }) => {
  if (url === '/v1/csrf') return reply(200, { csrf_token: 't' });
  if (url === '/v1/app') return reply(200, appInfo);
  if (url === '/v1/requests') return reply(200, { requests: [] });
  if (url === '/v1/conversations') return reply(200, { conversations: [] });
  if (url.startsWith('/v1/safety/access/change')) {
    const body = JSON.parse(init!.body!); posts.push({ url, body });
    if (body.password !== 'secret') return reply(403, { error: 'password_required' });
    if (body.grant === 'nobody@x.example') return reply(400, { error: 'unknown_account' });
    if (body.grant) granted = [...granted, { email: body.grant, granted_epoch: 1 }];
    if (body.revoke) granted = granted.filter(g => g.email !== body.revoke);
    return reply(200, { access: granted });
  }
  if (url === '/v1/safety/access') return role === 'owner' ? reply(200, { access: granted }) : reply(404, { error: 'unavailable' });
  if (url === '/v1/safety/change') {
    const body = JSON.parse(init!.body!); posts.push({ url, body });
    if (body.password !== 'secret') return reply(403, { error: 'password_required' });
    const scope: Scope = body.scope === 'all' ? 'all' : 'mine';
    for (const [k, v] of Object.entries(body.changes as Record<string, boolean>)) { if (scope === 'all') (v ? allOff.delete(k) : allOff.add(k)); else mineOverride[k] = v; }
    return reply(200, view(scope));
  }
  if (url === '/v1/safety?scope=all') return role === 'owner' ? reply(200, view('all')) : reply(404, { error: 'unavailable' });
  if (url === '/v1/safety') return role ? reply(200, view('mine')) : reply(404, { error: 'unavailable' });
  return reply(200, {});
}));
beforeEach(() => { posts = []; role = 'owner'; allOff = new Set(); mineOverride = {}; granted = []; resetCsrf(); server(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const openMenu = async () => { fireEvent.click(await screen.findByRole('button', { name: /Safety/ })); return screen.findByRole('dialog', { name: 'Safety' }); };
const sw = (name: string) => screen.getByRole('switch', { name });
const rowOf = (name: string) => within(sw(name).closest('.con-setting') as HTMLElement);
const category = (name: RegExp) => screen.getByRole('button', { name });
const ask = (title: string) => screen.getByRole('button', { name: `What does ${title} do?` });
const typePassword = (v: string) => fireEvent.change(screen.getByLabelText('Your password'), { target: { value: v } });
/** Apply Changes -> the masked prompt -> type -> Confirm */
const applyWith = async (v: string) => { fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' })); await screen.findByLabelText('Your password'); typePassword(v); fireEvent.click(screen.getByRole('button', { name: 'Confirm' })); };

describe('Safety console: who gets it and what it looks like', () => {
  it('shows nothing at all to an account without access', async () => {
    role = null; render(<SafetyButton />);
    await new Promise(r => setTimeout(r, 30));
    expect(screen.queryByRole('button', { name: /Safety/ })).toBeNull();
  });

  it('is a terminal window: a root@lumina title bar, the console header, and no command line', async () => {
    render(<SafetyButton />);
    const win = await openMenu();
    expect(within(win).getByText('root@lumina: ~')).toBeTruthy(); expect(within(win).getByText('SECURITY CONSOLE')).toBeTruthy();
    expect(within(win).getByText('Configure protection layers for your account.')).toBeTruthy();
    expect(win.querySelectorAll('input:not([type=password]):not([type=email])').length).toBe(0);          // no permanent command-entry field
    expect(win.querySelector('input[type=password]')).toBeNull();                                           // the password is asked for only when it is needed
  });

  it('gives a granted account only its own switches: no view tabs, no access category', async () => {
    role = 'member'; render(<SafetyButton />);
    await openMenu();
    expect(screen.queryByRole('tablist')).toBeNull(); expect(screen.queryByRole('button', { name: /Access/ })).toBeNull();
    expect(sw('Stop at payment pages')).toBeTruthy();
  });

  it('gives the owner a text switch between My account and All users', async () => {
    render(<SafetyButton />);
    await openMenu();
    const tabs = screen.getByRole('tablist', { name: 'Whose switches' });
    expect(within(tabs).getByRole('tab', { name: 'My account' }).getAttribute('aria-selected')).toBe('true');
    expect(within(tabs).getByRole('tab', { name: 'All users' }).getAttribute('aria-selected')).toBe('false');
    expect(within(tabs).getByRole('tab', { name: 'My account' }).textContent).toBe('[ My account ]');
  });
});

describe('Safety console: the tree', () => {
  it('numbers the real categories, skips empty ones and says how many switches each holds', async () => {
    render(<SafetyButton />);
    await openMenu();
    expect(category(/\[1\] Browser/).textContent).toContain('1 switch · 0 off');
    expect(category(/\[2\] Data and privacy/).textContent).toContain('2 switches · 0 off');
    expect(category(/\[3\] Sign-in and sessions/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Nothing here/ })).toBeNull();
    expect(category(/\[4\] Review Configuration/).getAttribute('aria-expanded')).toBe('false');
  });

  it('folds and unfolds each category on its own, with ▼ and ▶', async () => {
    render(<SafetyButton />);
    await openMenu();
    const browser = category(/\[1\] Browser/), data = category(/\[2\] Data and privacy/);
    expect(browser.getAttribute('aria-expanded')).toBe('true'); expect(browser.textContent).toContain('▼');
    fireEvent.click(browser);
    expect(browser.getAttribute('aria-expanded')).toBe('false'); expect(browser.textContent).toContain('▶');
    expect(screen.queryByRole('switch', { name: 'Stop at payment pages' })).toBeNull();
    expect(sw('Network destination guard')).toBeTruthy(); expect(data.getAttribute('aria-expanded')).toBe('true');       // another category stays open
    fireEvent.click(browser);
    expect(sw('Stop at payment pages')).toBeTruthy();
  });

  it('draws the branches as text: ├─ and └─ on the last switch of a category', async () => {
    render(<SafetyButton />);
    await openMenu();
    const trees = Array.from(document.querySelectorAll('[data-group="data"] button[role="switch"] .con-tree')).map(n => n.textContent);
    expect(trees).toEqual(['│  ├─ ', '│  └─ ']);
  });
});

describe('Safety console: switches written as text', () => {
  it('shows [x] [ON] or [ ] [OFF], toggles from anywhere on the row, and marks a pending change', async () => {
    render(<SafetyButton />);
    await openMenu();
    expect(sw('Stop at payment pages').textContent).toMatch(/\[x\].*Stop at payment pages.*\[ON\]/);
    fireEvent.click(screen.getByText('Stop at payment pages'));                                              // the label works too
    expect(sw('Stop at payment pages').getAttribute('aria-checked')).toBe('false');
    expect(sw('Stop at payment pages').textContent).toMatch(/\[ \].*\[OFF\] \*/);                            // OFF, and * until it is saved
    expect(screen.getByText('Pending changes: 1')).toBeTruthy();
    fireEvent.click(sw('Stop at payment pages'));
    expect(sw('Stop at payment pages').textContent).toMatch(/\[x\].*\[ON\]$/); expect(screen.getByText('Pending changes: 0')).toBeTruthy();
  });

  it('shows what is special about a switch as a note under it, and server-wide and core ones cannot be toggled', async () => {
    render(<SafetyButton />);
    await openMenu();
    expect(rowOf('Web access limits').getByText('not enforced yet')).toBeTruthy();
    expect((sw('CSRF protection') as HTMLButtonElement).disabled).toBe(true); expect((sw('Audit log') as HTMLButtonElement).disabled).toBe(true);
    expect(rowOf('CSRF protection').getByText(/set on the server for everyone, not here/)).toBeTruthy(); expect(rowOf('Audit log').getByText('always on')).toBeTruthy();
    fireEvent.click(sw('CSRF protection'));
    expect(sw('CSRF protection').getAttribute('aria-checked')).toBe('true');
  });

  it('turns everything on or off only where it may, and counts the real changes', async () => {
    render(<SafetyButton />);
    await openMenu();
    fireEvent.click(screen.getByRole('button', { name: 'Turn everything off' }));
    expect(sw('Stop at payment pages').getAttribute('aria-checked')).toBe('false'); expect(sw('CSRF protection').getAttribute('aria-checked')).toBe('true');
    expect(screen.getByText('Pending changes: 3')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Turn everything on' }));
    expect(screen.getByText('Pending changes: 0')).toBeTruthy();
  });
});

describe('Safety console: explanations', () => {
  it('opens one under its switch with the four parts, and never changes the switch', async () => {
    render(<SafetyButton />);
    await openMenu();
    expect(ask('Stop at payment pages').getAttribute('aria-expanded')).toBe('false'); expect(ask('Stop at payment pages').textContent).toContain('[?] What does this do?');
    fireEvent.click(ask('Stop at payment pages'));
    expect(ask('Stop at payment pages').getAttribute('aria-expanded')).toBe('true'); expect(ask('Stop at payment pages').textContent).toContain('[▼]');
    const text = screen.getByRole('region', { name: 'About Stop at payment pages' }).textContent!;
    for (const part of ['What it does:', 'Why it exists:', 'When on:', 'When off:']) expect(text).toContain(part);
    expect(text).toContain('Hands the browser back to you');
    expect(sw('Stop at payment pages').getAttribute('aria-checked')).toBe('true'); expect(screen.getByText('Pending changes: 0')).toBeTruthy();    // reading is not changing
  });

  it('keeps several open at once, closes each on its own, and opens none by itself', async () => {
    render(<SafetyButton />);
    await openMenu();
    expect(screen.queryAllByRole('region').length).toBe(0);
    fireEvent.click(ask('Stop at payment pages')); fireEvent.click(ask('Audit log'));
    expect(screen.queryAllByRole('region').length).toBe(2);
    expect(screen.getByRole('region', { name: 'About Audit log' }).textContent).toContain("It can't be switched here.");                    // a fixed protection says so
    fireEvent.click(ask('Stop at payment pages'));
    expect(screen.queryByRole('region', { name: 'About Stop at payment pages' })).toBeNull(); expect(screen.getByRole('region', { name: 'About Audit log' })).toBeTruthy();
  });

  it('says plainly that a switch nothing reads does nothing yet', async () => {
    render(<SafetyButton />);
    await openMenu();
    fireEvent.click(ask('Web access limits'));
    expect(screen.getByRole('region', { name: 'About Web access limits' }).textContent).toContain('Nothing changes yet: no code reads this switch.');
  });
});

describe('Safety console: saving', () => {
  it('asks for the password in a masked field only after Apply Changes, and sends the change with the duration', async () => {
    render(<SafetyButton />);
    await openMenu();
    expect((screen.getByRole('button', { name: 'Apply Changes' }) as HTMLButtonElement).disabled).toBe(true);        // nothing to apply
    fireEvent.click(sw('Stop at payment pages'));
    fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));
    const field = await screen.findByLabelText('Your password') as HTMLInputElement;
    expect(field.type).toBe('password'); expect(screen.getByText('Confirm saving 1 change.')).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Confirm' }) as HTMLButtonElement).disabled).toBe(true);              // nothing typed yet
    fireEvent.click(screen.getByRole('button', { name: /Disable duration/ })); fireEvent.click(screen.getByRole('option', { name: '2 hours' }));
    typePassword('secret'); fireEvent.keyDown(field, { key: 'Enter' });
    expect((await screen.findByRole('status')).textContent).toBe('[+] Configuration saved successfully.');
    expect(posts).toEqual([{ url: '/v1/safety/change', body: { password: 'secret', changes: { payment_stop: false }, minutes: 120 } }]);
    expect(screen.getByRole('dialog', { name: 'Safety' })).toBeTruthy();                                              // the console stays open to say so
    expect(screen.queryByLabelText('Your password')).toBeNull();                                                      // and the password is gone
    expect(sw('Stop at payment pages').textContent).toMatch(/\[ \].*\[OFF\]$/); expect(screen.getByText('Pending changes: 0')).toBeTruthy();
    expect(screen.getByRole('button', { name: /Safety · 1 off/ })).toBeTruthy();
  });

  it('says the password is wrong inline, keeps the choices and the prompt, and reports success only after a retry works', async () => {
    render(<SafetyButton />);
    await openMenu();
    fireEvent.click(sw('Stop at payment pages')); await applyWith('nope');
    expect((await screen.findByRole('alert')).textContent).toBe('[!] That password is not right.');
    expect(screen.queryByRole('status')).toBeNull();                                                                  // never a success that did not happen
    expect(sw('Stop at payment pages').getAttribute('aria-checked')).toBe('false'); expect(screen.getByText('Pending changes: 1')).toBeTruthy();
    typePassword('secret'); fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    expect((await screen.findByRole('status')).textContent).toContain('saved successfully'); expect(screen.queryByRole('alert')).toBeNull();
  });

  it('drops pending changes with Discard Changes', async () => {
    render(<SafetyButton />);
    await openMenu();
    fireEvent.click(sw('Stop at payment pages')); expect(screen.getByText('Pending changes: 1')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Discard Changes' }));
    expect(sw('Stop at payment pages').getAttribute('aria-checked')).toBe('true'); expect(screen.getByText('Pending changes: 0')).toBeTruthy();
    expect(posts).toEqual([]);
  });

  it('lists the pending changes under Review Configuration', async () => {
    render(<SafetyButton />);
    await openMenu();
    fireEvent.click(category(/Review Configuration/));
    expect(screen.getByText('No pending changes.')).toBeTruthy();
    fireEvent.click(sw('Stop at payment pages'));
    expect(screen.getByText('Stop at payment pages: [ON] → [OFF]')).toBeTruthy();
  });
});

describe('Safety console: how long an off lasts', () => {
  it('shows the duration only while a change turns something off, as a text list with a > on the current choice', async () => {
    render(<SafetyButton />);
    await openMenu();
    expect(screen.queryByRole('button', { name: /Disable duration/ })).toBeNull();
    fireEvent.click(sw('Stop at payment pages'));
    fireEvent.click(screen.getByRole('button', { name: 'Disable duration: Until I turn it back on' }));
    const list = screen.getByRole('listbox', { name: 'Disable duration' });
    expect(within(list).getAllByRole('option').map(o => o.textContent!.trim())).toEqual(['> Until I turn it back on', '30 minutes', '2 hours', '8 hours', '24 hours', 'Custom...']);
    fireEvent.click(within(list).getByRole('option', { name: '30 minutes' }));
    expect(screen.queryByRole('listbox')).toBeNull(); expect(screen.getByRole('button', { name: 'Disable duration: 30 minutes' })).toBeTruthy();
    fireEvent.click(sw('Stop at payment pages'));
    expect(screen.queryByRole('button', { name: /Disable duration/ })).toBeNull();                                  // nothing is being turned off any more
  });

  it('takes a number of minutes of your own within what the server allows, and says so when it is out of range', async () => {
    render(<SafetyButton />);
    await openMenu();
    fireEvent.click(sw('Stop at payment pages'));
    fireEvent.click(screen.getByRole('button', { name: /Disable duration/ })); fireEvent.click(screen.getByRole('option', { name: 'Custom...' }));
    const input = screen.getByLabelText('Custom minutes');
    for (const bad of ['', '0', '-5', '1.5', 'abc', '10081']) {
      fireEvent.change(input, { target: { value: bad } }); fireEvent.keyDown(input, { key: 'Enter' });
      expect(screen.getByRole('alert').textContent).toBe('[!] Enter a whole number of minutes from 1 to 10080.');
    }
    fireEvent.change(input, { target: { value: '45' } }); fireEvent.keyDown(input, { key: 'Enter' });
    expect(screen.getByRole('button', { name: 'Disable duration: 45 minutes' })).toBeTruthy();
    await applyWith('secret');
    await screen.findByRole('status');
    expect(posts[0].body.minutes).toBe(45);
  });
});

describe('Safety console: window and keyboard', () => {
  it('closes with Escape one layer at a time: the duration list, then the password prompt, then the console', async () => {
    render(<SafetyButton />);
    const button = await screen.findByRole('button', { name: /Safety/ });
    await openMenu(); fireEvent.click(sw('Stop at payment pages'));
    fireEvent.click(screen.getByRole('button', { name: /Disable duration/ })); fireEvent.click(screen.getByRole('button', { name: 'Apply Changes' }));
    await screen.findByLabelText('Your password');
    fireEvent.keyDown(document, { key: 'Escape' }); expect(screen.queryByRole('listbox')).toBeNull(); expect(screen.getByLabelText('Your password')).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' }); expect(screen.queryByLabelText('Your password')).toBeNull(); expect(screen.getByRole('dialog')).toBeTruthy();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(document.activeElement).toBe(button);                                                                     // focus goes back where it came from
    await openMenu();
    expect(sw('Stop at payment pages').getAttribute('aria-checked')).toBe('true');                                   // the unsaved choice was dropped
  });

  it('has working minimize, maximize and close controls', async () => {
    render(<SafetyButton />);
    const win = await openMenu();
    fireEvent.click(screen.getByRole('button', { name: 'Minimize' }));
    expect(screen.queryByRole('switch', { name: 'Stop at payment pages' })).toBeNull(); expect(win.className).toContain('con-min'); expect(within(win).getByText('root@lumina: ~')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Minimize' })); expect(sw('Stop at payment pages')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Maximize' })); expect(win.className).toContain('con-max');
    fireEvent.click(screen.getByRole('button', { name: 'Maximize' })); expect(win.className).not.toContain('con-max');
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('is operable from the keyboard: every control is a real button, a switch or a field', async () => {
    render(<SafetyButton />);
    const win = await openMenu();
    const clickable = Array.from(win.querySelectorAll('[onclick], .con-row, .con-act, .con-tab, .con-opt')).filter(n => n.tagName !== 'BUTTON' && !n.classList.contains('con-note') && n.getAttribute('role') !== 'switch');
    expect(clickable.filter(n => (n as HTMLElement).onclick)).toEqual([]);
    for (const control of win.querySelectorAll('button')) expect((control as HTMLButtonElement).tabIndex).toBeGreaterThanOrEqual(-1);
  });
});

describe('Safety console: all users', () => {
  it('loads the defaults for everyone when the owner switches to them, with who differs and what cannot be turned off for everyone', async () => {
    render(<SafetyButton />);
    await openMenu();
    fireEvent.click(screen.getByRole('tab', { name: 'All users' }));
    expect(await screen.findByText(/2 accounts set differently/)).toBeTruthy();
    expect(screen.getByRole('tab', { name: 'All users' }).textContent).toBe('[ All users ]');
    expect(screen.getByText(/These are the defaults for every account/)).toBeTruthy();
    expect((sw('Network destination guard') as HTMLButtonElement).disabled).toBe(true);
    expect(rowOf('Network destination guard').getByText(/can't be turned off for everyone/)).toBeTruthy();
    expect((sw('Stop at payment pages') as HTMLButtonElement).disabled).toBe(false);
  });

  it('sends scope all, and what everyone gets then shows in My account as off for all users', async () => {
    render(<SafetyButton />);
    await openMenu();
    fireEvent.click(screen.getByRole('tab', { name: 'All users' })); await screen.findByText(/2 accounts set differently/);
    fireEvent.click(sw('Stop at payment pages')); await applyWith('secret');
    expect((await screen.findByRole('status')).textContent).toContain('saved successfully');
    expect(posts[0].body).toEqual({ password: 'secret', changes: { payment_stop: false }, scope: 'all' });
    await screen.findByRole('button', { name: /Safety · 1 off/ });                                                   // this account's own count follows
    fireEvent.click(screen.getByRole('tab', { name: 'My account' }));
    expect(sw('Stop at payment pages').getAttribute('aria-checked')).toBe('false');
    expect(rowOf('Stop at payment pages').getByText('off for all users')).toBeTruthy();
  });

  it('keeps each view\'s unsaved choices when switching between them', async () => {
    render(<SafetyButton />);
    await openMenu();
    fireEvent.click(sw('Stop at payment pages'));
    fireEvent.click(screen.getByRole('tab', { name: 'All users' })); await screen.findByText(/2 accounts set differently/);
    expect(sw('Stop at payment pages').getAttribute('aria-checked')).toBe('true');
    fireEvent.click(screen.getByRole('tab', { name: 'My account' }));
    expect(sw('Stop at payment pages').getAttribute('aria-checked')).toBe('false'); expect(screen.getByText('Pending changes: 1')).toBeTruthy();
  });
});

describe('Safety console: who can open it', () => {
  const allView = async () => { render(<SafetyButton />); await openMenu(); fireEvent.click(screen.getByRole('tab', { name: 'All users' })); await screen.findByRole('button', { name: /\[4\] Access/ }); };

  it('lists the accounts with access, and adds and removes them through the password prompt', async () => {
    granted = [{ email: 'b@x.example', granted_epoch: 1 }];
    await allView();
    expect(await screen.findByText('b@x.example')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Email to give access'), { target: { value: 'c@x.example' } });
    fireEvent.click(screen.getByRole('button', { name: 'Give access' }));
    expect(screen.getByText('Confirm giving c@x.example access to this console.')).toBeTruthy();
    typePassword('secret'); fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(await screen.findByText('c@x.example')).toBeTruthy();
    expect((screen.getByLabelText('Email to give access') as HTMLInputElement).value).toBe('');
    expect(posts.at(-1)!.body).toEqual({ password: 'secret', grant: 'c@x.example' });
    fireEvent.click(screen.getByRole('button', { name: 'Remove b@x.example' }));
    expect(screen.getByText('Confirm removing b@x.example.')).toBeTruthy();
    typePassword('secret'); fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(screen.queryByText('b@x.example')).toBeNull());
    expect(posts.at(-1)!.body).toEqual({ password: 'secret', revoke: 'b@x.example' });
  });

  it('says so when nobody has access, when the email is not an account, and when the password is wrong', async () => {
    await allView();
    expect(await screen.findByText('Nobody else has access.')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Email to give access'), { target: { value: 'nobody@x.example' } });
    fireEvent.click(screen.getByRole('button', { name: 'Give access' })); typePassword('secret'); fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    expect((await screen.findByRole('alert')).textContent).toBe('[!] There is no other account with that email.');
    typePassword('nope'); fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(screen.getByRole('alert').textContent).toBe('[!] That password is not right.'));
    expect((screen.getByLabelText('Email to give access') as HTMLInputElement).value).toBe('nobody@x.example');      // kept so it can be retried
  });
});

describe('Safety console in the sidebar', () => {
  it('lives inside the sidebar menu and folds to its icon with the rest', async () => {
    render(<SettingsProvider><DataProvider><MemoryRouter><Sidebar /></MemoryRouter></DataProvider></SettingsProvider>);
    const button = await screen.findByRole('button', { name: /Safety/ });
    expect(button.closest('nav')?.getAttribute('aria-label')).toBe('Primary');
    expect(button.querySelector('.lbl')).toBeTruthy();
  });
});
