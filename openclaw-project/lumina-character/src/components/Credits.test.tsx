import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import Credits, { OPENMOJI_CREDIT } from './Credits';

afterEach(cleanup);

describe('Credits', () => {
  it('shows the exact credit sentence OpenMoji requires', () => {
    const { container } = render(<Credits />);
    expect(OPENMOJI_CREDIT).toBe('Emoji graphics by OpenMoji (https://openmoji.org), licensed under CC BY-SA 4.0 (https://creativecommons.org/licenses/by-sa/4.0/).');
    expect(container.textContent).toContain(OPENMOJI_CREDIT);
  });

  it('links to OpenMoji and the license, opening safely in a new tab', () => {
    const { container } = render(<Credits />);
    const hrefs = [...container.querySelectorAll('a')].map(a => a.getAttribute('href'));
    expect(hrefs).toContain('https://openmoji.org'); expect(hrefs).toContain('https://creativecommons.org/licenses/by-sa/4.0/');
    for (const a of container.querySelectorAll('a')) { expect(a.getAttribute('target')).toBe('_blank'); expect(a.getAttribute('rel')).toContain('noopener'); }
  });
});
