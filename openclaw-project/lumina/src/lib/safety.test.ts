import { afterEach, describe, expect, it, vi } from 'vitest';
import { allDraft, canSet, changeAccess, changeSafety, changesOf, draftOf, explainSafetyError, loadAccess, loadSafety, notesOf, requestBody, switchable, type SafetyFeature, type SafetyState } from './safety';
import { ApiError, resetCsrf } from './api';
import { HELP, helpFor } from './safetyHelp';

const f = (over: Partial<SafetyFeature> & { key: string }): SafetyFeature =>
  ({ group: 'a', title: over.key, plain: `${over.key} plain`, wired: true, on: true, expires_epoch: null, source: 'default', lock: null, ...over });
const state: SafetyState = {
  role: 'owner', scope: 'mine', scopes: ['mine', 'all'], groups: [{ key: 'a', title: 'A' }],
  features: [f({ key: 'one' }), f({ key: 'two', on: false, wired: false, source: 'account' }), f({ key: 'three', lock: 'shared' }), f({ key: 'four', lock: 'core' }),
    f({ key: 'five', lock: 'privacy' }), f({ key: 'six', lock: 'privacy', on: false })],
  off_count: 2,
};
const reply = (status: number, body: unknown) => ({ ok: status < 400, status, json: async () => body });
afterEach(() => { vi.unstubAllGlobals(); resetCsrf(); });

describe('safety helpers', () => {
  it('start from what the server has and report only real differences', () => {
    const draft = draftOf(state);
    expect(draft).toEqual({ one: true, two: false, three: true, four: true, five: true, six: false });
    expect(changesOf(state, draft)).toEqual({});
    expect(changesOf(state, { ...draft, one: false })).toEqual({ one: false });
    expect(changesOf(state, { one: false })).toEqual({ one: false });                               // a switch missing from the draft is not a change
  });
  it('know which switches can be set which way', () => {
    const [one, , three, four, five, six] = [0, 1, 2, 3, 4, 5].map(i => state.features[i]);
    expect([canSet(one, true), canSet(one, false)]).toEqual([true, true]);
    expect([canSet(three, true), canSet(three, false)]).toEqual([false, false]);                  // shared: never here
    expect([canSet(four, true), canSet(four, false)]).toEqual([false, false]);                    // core: never
    expect([canSet(five, true), canSet(five, false)]).toEqual([true, false]);                     // privacy: back on yes, off no
    expect([switchable(one), switchable(three), switchable(four), switchable(five), switchable(six)]).toEqual([true, false, false, false, true]);   // a privacy switch that is off can be turned on
  });
  it('turn everything on or off only where that is allowed', () => {
    expect(allDraft(state, false)).toEqual({ one: false, two: false, three: true, four: true, five: true, six: false });
    expect(allDraft(state, true)).toEqual({ one: true, two: true, three: true, four: true, five: true, six: true });
  });
  it('say in plain words what is special about a switch', () => {
    const [one, two, three, four, five, six] = state.features;
    expect(notesOf(one, 'mine')).toEqual([]);
    expect(notesOf(two, 'mine')).toEqual(['not enforced yet']);
    expect(notesOf(three, 'all')).toEqual(['set on the server for everyone, not here']);
    expect(notesOf(f({ key: 'x', lock: 'shared', wired: false }), 'all')).toEqual(['set on the server for everyone, not here']);        // no "not enforced yet" on what this menu never enforces
    expect(notesOf(f({ key: 'x', lock: 'core', wired: false }), 'mine')).toEqual(['always on']);
    expect(notesOf(f({ key: 'x', lock: 'privacy', wired: false }), 'mine')[0]).toBe('not enforced yet');
    expect(notesOf(four, 'mine')).toEqual(['always on']);
    expect(notesOf(five, 'all')[0]).toMatch(/can't be turned off for everyone/);
    expect(notesOf(six, 'all')[0]).toMatch(/turn it back on/);
    expect(notesOf(f({ key: 'x', on: false, source: 'all' }), 'mine')).toEqual(['off for all users']);
    expect(notesOf(f({ key: 'x', overridden: 1 }), 'all')).toEqual(['1 account set differently']);
    expect(notesOf(f({ key: 'x', overridden: 3 }), 'all')).toEqual(['3 accounts set differently']);
  });
  it('send a duration only when something is being turned off, and the scope only for all users', () => {
    expect(requestBody('pw', { one: false }, 30)).toEqual({ password: 'pw', changes: { one: false }, minutes: 30 });
    expect(requestBody('pw', { two: true }, 30)).toEqual({ password: 'pw', changes: { two: true } });
    expect(requestBody('pw', { one: false }, 0, 'all')).toEqual({ password: 'pw', changes: { one: false }, scope: 'all' });
    expect(requestBody('pw', { one: false }, 5, 'mine')).toEqual({ password: 'pw', changes: { one: false }, minutes: 5 });
  });
});

describe('safety calls', () => {
  it('load nothing for an account without access or for an answer that is not a switch list', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(404, { error: 'unavailable' }))); expect(await loadSafety()).toBeNull();
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, { features: 'nope' }))); expect(await loadSafety()).toBeNull();
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, { features: [] }))); expect(await loadSafety()).toBeNull();           // groups are needed too
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); })); expect(await loadSafety()).toBeNull();
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, state))); expect(await loadSafety()).toEqual(state);
  });
  it('ask for the all-users view with the scope in the address', async () => {
    const urls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => { urls.push(url); return reply(200, state); }));
    await loadSafety(); await loadSafety('mine'); await loadSafety('all');
    expect(urls).toEqual(['/v1/safety', '/v1/safety', '/v1/safety?scope=all']);
  });
  it('post a change with the password and scope, and an access change with the password', async () => {
    const calls: { url: string; body?: string }[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: { body?: string }) => {
      calls.push({ url, body: init?.body });
      return reply(200, url === '/v1/csrf' ? { csrf_token: 't' } : url.startsWith('/v1/safety/access') ? { access: [{ email: 'b@x.example', granted_epoch: 1 }] } : state);
    }));
    await changeSafety('pw', { one: false }, 120, 'all');
    expect(calls.at(-1)!.url).toBe('/v1/safety/change'); expect(JSON.parse(calls.at(-1)!.body!)).toEqual({ password: 'pw', changes: { one: false }, minutes: 120, scope: 'all' });
    expect(await changeAccess('pw', { grant: 'b@x.example' })).toEqual([{ email: 'b@x.example', granted_epoch: 1 }]);
    expect(calls.at(-1)!.url).toBe('/v1/safety/access/change'); expect(JSON.parse(calls.at(-1)!.body!)).toEqual({ password: 'pw', grant: 'b@x.example' });
    expect(await loadAccess()).toEqual([{ email: 'b@x.example', granted_epoch: 1 }]);
  });
  it('load no access list when the server refuses or answers oddly', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reply(404, {}))); expect(await loadAccess()).toBeNull();
    vi.stubGlobal('fetch', vi.fn(async () => reply(200, { access: 'x' }))); expect(await loadAccess()).toBeNull();
  });
  it('explain a refusal plainly', () => {
    expect(explainSafetyError(new ApiError('password_required', 403))).toBe('That password is not right.');
    expect(explainSafetyError(new ApiError('locked', 400))).toBe('That switch cannot be changed here.');
    expect(explainSafetyError(new ApiError('unknown_account', 400))).toBe('There is no other account with that email.');
    expect(explainSafetyError(new ApiError('x', 500))).toBe('That was not accepted. Try again.');
    expect(explainSafetyError(new Error('x'))).toBe('That was not accepted. Try again.');
  });
});

describe('the explanations', () => {
  it('give every switch all four parts, in plain sentences', () => {
    for (const [key, h] of Object.entries(HELP)) {
      for (const part of ['does', 'why', 'on', 'off'] as const) {
        expect(h[part].trim().length, `${key}.${part}`).toBeGreaterThan(8);
        expect(h[part].trim(), `${key}.${part}`).toMatch(/[.)]$/);
      }
    }
  });
  it('say so when a switch is fixed or nothing reads it, and never promise what the code does not do', () => {
    expect(HELP.audit_log.off).toContain("can't be switched here");
    expect(HELP.routing_policy.on).toContain('no code reads this switch');
    expect(HELP.cell_limits.off).toContain('Set on the server');
    expect(HELP.vault_notice.off).toContain('never stored');                         // a card security code stays out whatever the switch says
    expect(HELP.ssrf_guard.off).toContain('firewall');                                // the network firewall stays on whatever the switch says
  });
  it('fall back to the one-line description for a switch it does not know, and say what is not known', () => {
    const unknown = f({ key: 'brand_new', plain: 'Does a new thing.', wired: false });
    expect(helpFor(unknown).does).toBe('Does a new thing.'); expect(helpFor(unknown).on).toContain('no code reads this switch');
    expect(helpFor(f({ key: 'brand_new', plain: 'x', wired: true })).on).toBe('The protection applies.');
    expect(helpFor(f({ key: 'payment_stop' })).does).toBe(HELP.payment_stop.does);
  });
});
