import { afterEach, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ComparisonCard } from './Cards';
afterEach(cleanup);
it('migrates four historical options into the registry and preserves source links', async () => {
  render(<ComparisonCard spec={{ schemaVersion: '1.0', type: 'comparison', title: 'Toothbrushes', items: ['One', 'Two', 'Three', 'Four'].map(name => ({ name, facts: [], pros: [], cons: [], link: 'https://example.com' })) }} />);
  expect(await screen.findByText('One')).toBeTruthy();
  expect(document.querySelectorAll('article').length).toBe(4);
  expect(screen.getAllByRole('link').length).toBe(4);
  expect(document.querySelector('.t-card_grid')).not.toBeNull();
});
