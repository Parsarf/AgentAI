import { ApiError } from '../lib/api';

/** Only fixed, customer-safe messages. Never echo server exceptions or submitted values. */
export function interactionError(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Could not connect. Your answers are kept in this tab. Check your connection and try again.';
  if (error.status === 401) return 'Your session expired. Sign in again before continuing.';
  if (error.code === 'csrf_denied') return 'Your security token expired. Sign in again before continuing.';
  if (error.status === 402) return error.category === 'queue_full' ? 'Your waiting queue is full. Wait for a task to finish, then try again.' : 'This task could not be admitted within your usage allowance. Check Usage before trying again.';
  if (error.status === 409) return 'This answer changed in another tab or while the assistant was working. Review the latest saved version before continuing.';
  if (error.status === 429) return 'Too many requests. Wait a moment before trying again. Your answers are kept in this tab.';
  if (error.status === 403) return 'This action is no longer permitted. Your answers are kept in this tab.';
  if (error.status === 404) return 'This answer or task is no longer available to your account.';
  if (error.status >= 500) return 'Lumina is temporarily unavailable. Your answers are kept in this tab; try again shortly.';
  if (error.status === 400) return 'Some values were rejected. Check the highlighted fields and try again.';
  return 'The action could not be completed. Your answers are kept in this tab; try again.';
}
export function failureCategory(error: unknown): string {
  return error instanceof ApiError ? ({ 400: 'validation', 401: 'session', 402: 'admission', 403: 'permission', 404: 'unavailable', 409: 'conflict', 429: 'rate_limit' }[error.status] ?? 'server') : 'network';
}
