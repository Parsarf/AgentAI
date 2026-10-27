import { beforeEach, describe, expect, it } from 'vitest';
import { getAnswerStyle, setAnswerStyle, STYLES } from './answerStyle';

describe('answer style', () => {
  beforeEach(() => localStorage.clear());
  it('defaults to medium and remembers a choice', () => { expect(getAnswerStyle()).toBe('medium'); setAnswerStyle('basic'); expect(getAnswerStyle()).toBe('basic'); setAnswerStyle('interactive'); expect(getAnswerStyle()).toBe('interactive'); });
  it('ignores a stored value it does not know (ultra is not available)', () => { localStorage.setItem('lumina.answerStyle', 'ultra'); expect(getAnswerStyle()).toBe('medium'); expect(STYLES).not.toContain('ultra' as never); });
});
