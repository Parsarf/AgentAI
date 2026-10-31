import { useSyncExternalStore } from 'react';

/** How much interface the assistant may put in an answer. Sent with every message; the server enforces it too.
 *  basic: plain text only. medium: tables, charts and cards that only show information. interactive: also forms, buttons and live task widgets. */
export const STYLES = ['basic', 'medium', 'interactive'] as const;
export type AnswerStyle = (typeof STYLES)[number];
export const STYLE_INFO: Record<AnswerStyle, { label: string; hint: string }> = {
  basic: { label: 'Basic', hint: 'Plain text answers only. The fastest and cheapest.' },
  medium: { label: 'Medium', hint: 'Adds tables, charts and cards that show information.' },
  interactive: { label: 'Interactive', hint: 'Adds forms, buttons, approvals and live task progress.' },
};
const KEY = 'lumina.answerStyle'; const EVENT = 'lumina:answer-style';

export function getAnswerStyle(): AnswerStyle {
  try { const v = localStorage.getItem(KEY); return (STYLES as readonly string[]).includes(v ?? '') ? (v as AnswerStyle) : 'medium'; } catch { return 'medium'; }
}
export function setAnswerStyle(v: AnswerStyle) {
  try { localStorage.setItem(KEY, v); } catch { /* private mode: the choice lasts until reload */ }
  window.dispatchEvent(new Event(EVENT));
}
const subscribe = (cb: () => void) => { window.addEventListener(EVENT, cb); window.addEventListener('storage', cb); return () => { window.removeEventListener(EVENT, cb); window.removeEventListener('storage', cb); }; };
export const useAnswerStyle = (): [AnswerStyle, (v: AnswerStyle) => void] => [useSyncExternalStore(subscribe, getAnswerStyle, () => 'medium' as AnswerStyle), setAnswerStyle];
