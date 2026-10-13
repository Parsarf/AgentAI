import { describe, expect, it } from 'vitest';
import { ApiError } from './api';
import { codeFromLocation, signInMessage, signUpMessage } from './signup';

describe('sign-up helpers', () => {
  it('tells people honestly why they cannot come in yet, without hints otherwise', () => {
    expect(signInMessage(new ApiError('pending_approval', 403))).toMatch(/waiting for approval/);
    expect(signInMessage(new ApiError('not_approved', 403))).toMatch(/not approved/);
    expect(signInMessage(new ApiError('invalid_credentials', 401))).toBe('Those details did not work.');
    expect(signInMessage(new ApiError('x', 429))).toMatch(/Too many/);
    expect(signInMessage(new Error('network'))).toBe('Those details did not work.');
  });
  it('explains sign-up problems', () => {
    expect(signUpMessage(new ApiError('weak_password', 400))).toMatch(/password/);
    expect(signUpMessage(new ApiError('signups_closed', 403))).toMatch(/closed/);
    expect(signUpMessage(new ApiError('x', 429))).toMatch(/Too many/);
  });
  it('reads the confirmation code only from /verify with a plausible code', () => {
    expect(codeFromLocation('/app/verify', '?code=abcdefghijklmnop1234')).toBe('abcdefghijklmnop1234');
    expect(codeFromLocation('/app/chat', '?code=abcdefghijklmnop1234')).toBeNull();
    expect(codeFromLocation('/app/verify', '?code=short')).toBeNull();
    expect(codeFromLocation('/app/verify', '')).toBeNull();
  });
});
