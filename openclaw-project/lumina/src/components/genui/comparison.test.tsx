import { afterEach, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ComparisonCard } from './Cards';
afterEach(cleanup);
it('exposes four options for balanced layout and keeps selection separate from links', () => {
  render(<ComparisonCard spec={{ schemaVersion: '1.0', type: 'comparison', title: 'Toothbrushes', items: ['One', 'Two', 'Three', 'Four'].map(name => ({ name, facts: [], pros: [], cons: [], link: 'https://example.com' })) }} />);
  expect(document.querySelector('.gcompare')?.getAttribute('data-count')).toBe('4');
  expect(document.querySelectorAll('article').length).toBe(4);
  const select = screen.getByRole('button', { name: 'Select One' });
  fireEvent.click(select); expect(select.getAttribute('aria-pressed')).toBe('true');
  fireEvent.click(select); expect(select.getAttribute('aria-pressed')).toBe('false');
  expect(screen.getAllByRole('link').length).toBe(4);
});
