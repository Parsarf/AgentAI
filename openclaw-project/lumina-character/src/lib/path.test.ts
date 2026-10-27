import { describe, expect, it } from 'vitest';
import { canonical } from './path';

describe('canonical', () => {
  it('moves the site root to /app/', () => { expect(canonical('/')).toBe('/app/'); });
  it('keeps query and hash', () => { expect(canonical('/', '?a=1', '#x')).toBe('/app/?a=1#x'); });
  it('maps other paths under /app', () => { expect(canonical('/tasks/r1')).toBe('/app/tasks/r1'); });
  it('leaves /app paths alone and fixes the bare /app', () => {
    expect(canonical('/app/')).toBeNull(); expect(canonical('/app/tasks')).toBeNull(); expect(canonical('/app')).toBe('/app/');
  });
});
