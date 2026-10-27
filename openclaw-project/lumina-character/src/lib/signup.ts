import { ApiError } from './api';

/** What a person is told when sign-in is refused. Honest about waiting for approval; never reveals whether an email exists. */
export function signInMessage(x: unknown): string {
  if (x instanceof ApiError) {
    if (x.status === 429) return 'Too many attempts. Wait a few minutes.';
    if (x.code === 'pending_approval') return 'Your email is confirmed and your account is waiting for approval. We will email you as soon as it is ready.';
    if (x.code === 'not_approved') return 'Your sign-up was not approved. If you think this is a mistake, reply to the email you received.';
  }
  return 'Those details did not work.';
}

export function signUpMessage(x: unknown): string {
  if (x instanceof ApiError) {
    if (x.status === 429) return 'Too many sign-ups from here. Please try again later.';
    if (x.code === 'weak_password') return 'Choose a longer, less common password (at least 12 characters is best).';
    if (x.code === 'invalid_email') return 'That does not look like an email address.';
    if (x.code === 'signups_closed') return 'Sign-ups are closed right now.';
    if (x.code === 'signups_full') return 'We are full right now. Please try again later.';
  }
  return 'Could not create the account. Check your connection and try again.';
}

/** The confirmation link carries the code in the query string: /app/verify?code=... */
export function codeFromLocation(pathname: string, search: string): string | null {
  if (!/\/verify\/?$/.test(pathname)) return null;
  const code = new URLSearchParams(search).get('code');
  return code && /^[A-Za-z0-9_-]{16,128}$/.test(code) ? code : null;
}
