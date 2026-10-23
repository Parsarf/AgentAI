import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { ChartCard, ComparisonCard, TableCard } from './Cards';
import { chartSpec, comparisonSpec, tableSpec } from '../../lib/genui/data';
import { ChatActionsContext } from '../../lib/chatActions';
afterEach(cleanup);
it('exposes four options for balanced layout and draws each link once', () => {
  render(<ComparisonCard spec={{ schemaVersion: '1.0', type: 'comparison', title: 'Toothbrushes', items: ['One', 'Two', 'Three', 'Four'].map(name => ({ name, facts: [], pros: [], cons: [], link: 'https://example.com' })) }} />);
  expect(document.querySelector('.gcompare')?.getAttribute('data-count')).toBe('4');
  expect(document.querySelectorAll('article').length).toBe(4);
  expect(screen.queryByRole('button')).toBeNull();                                            // no fixed buttons: a card without follow-ups has none
  expect(screen.getAllByRole('link').length).toBe(4);
});

const ID = 'ab'.repeat(16);
const two = (first: object = {}) => ({ schemaVersion: '1.0' as const, type: 'comparison' as const, title: 'Rackets', items: [{ name: 'Vanguard', facts: [], pros: [], cons: [], ...first }, { name: 'Gearbox', facts: [], pros: [], cons: [] }] });

it('shows an option picture from our own origin, with the source under it, and leaves other options as they were', () => {
  render(<ComparisonCard spec={two({ image: { id: ID, w: 400, h: 300, source: 'shop.example' } })} />);
  const img = screen.getByAltText('Vanguard') as HTMLImageElement;
  expect(img.getAttribute('src')).toBe(`/v1/media/${ID}`);
  expect(screen.getByText('shop.example')).toBeTruthy();
  expect(document.querySelectorAll('.gopt-img').length).toBe(1);
  expect(screen.queryByAltText('Gearbox')).toBeNull();
});

it('drops the picture quietly if it cannot be loaded', () => {
  render(<ComparisonCard spec={two({ image: { id: ID, source: 'shop.example' } })} />);
  fireEvent.error(screen.getByAltText('Vanguard'));
  expect(document.querySelector('.gopt-img')).toBeNull();
  expect(screen.getByRole('heading', { name: 'Vanguard' })).toBeTruthy();                      // the option itself is still there
});

it('accepts only a well-formed image reference in the card schema', () => {
  const good = comparisonSpec.safeParse(two({ image: { id: ID, w: 400, h: 300, source: 'shop.example' } }));
  expect(good.success).toBe(true);
  for (const image of [{ id: 'https://evil.example/x.png', source: 's' }, { id: ID.toUpperCase(), source: 's' }, { id: ID, source: 's', url: 'https://evil.example/x' }, { id: ID }, 'https://evil.example/x.png']) {
    expect(comparisonSpec.safeParse(two({ image })).success).toBe(false);
  }
  expect(comparisonSpec.safeParse(two()).success).toBe(true);
});

const shop = (extra: object = {}, first: object = {}) => ({ ...two({ price: '$199', actions: ['Show the reviews for Vanguard', 'Is Vanguard in stock near me?'], ...first }), ...extra });

it('draws no follow-ups outside a chat, and no fixed button anywhere', () => {
  render(<ComparisonCard spec={shop()} />);
  expect(screen.queryByRole('button')).toBeNull();
  expect(screen.queryByText(/cheapest reliable/i)).toBeNull();
});

it('draws the assistant\'s follow-ups under their own option and sends exactly the sentence on the button, once', async () => {
  const send = vi.fn().mockResolvedValue(undefined);
  render(<ChatActionsContext.Provider value={{ send }}><ComparisonCard spec={shop()} /></ChatActionsContext.Provider>);
  expect(screen.getAllByRole('button').map(b => b.textContent)).toEqual(['Show the reviews for Vanguard', 'Is Vanguard in stock near me?']);   // the other option had none
  const reviews = screen.getByText('Show the reviews for Vanguard');
  fireEvent.click(reviews); fireEvent.click(reviews);
  await screen.findByText('✓ Show the reviews for Vanguard');
  expect(send).toHaveBeenCalledTimes(1); expect(send).toHaveBeenCalledWith('Show the reviews for Vanguard');
  expect((screen.getByText('✓ Show the reviews for Vanguard') as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByText('Is Vanguard in stock near me?') as HTMLButtonElement).disabled).toBe(false);                  // the others stay available
});

it('lets the person try again when a follow-up does not go through', async () => {
  const send = vi.fn().mockRejectedValueOnce(new Error('down')).mockResolvedValue(undefined);
  render(<ChatActionsContext.Provider value={{ send }}><ComparisonCard spec={shop()} /></ChatActionsContext.Provider>);
  fireEvent.click(screen.getByText('Is Vanguard in stock near me?'));
  await screen.findByText('That did not go through. Try again.');
  fireEvent.click(screen.getByText('Is Vanguard in stock near me?'));
  await screen.findByText('✓ Is Vanguard in stock near me?'); expect(send).toHaveBeenCalledTimes(2);
});

it('shows card-level follow-ups on every kind of card, and what is offered differs from card to card', () => {
  const send = vi.fn().mockResolvedValue(undefined);
  const table = tableSpec.parse({ schemaVersion: '1.0', type: 'table', title: 'Pizza', columns: [{ id: 'n', label: 'Name' }], rows: [{ n: 'A' }], actions: ['Only places open now'] });
  const chart = chartSpec.parse({ schemaVersion: '1.0', type: 'chart', chart: 'bar', title: 'Cost', labels: ['a'], series: [{ name: 's', values: [1] }], actions: ['Break this down by month'] });
  const cmp = comparisonSpec.parse(shop({ actions: ['Narrow to under $150'] }, {}));
  render(<ChatActionsContext.Provider value={{ send }}><TableCard spec={table} /><ChartCard spec={chart} /><ComparisonCard spec={cmp} /></ChatActionsContext.Provider>);
  for (const text of ['Only places open now', 'Break this down by month', 'Narrow to under $150']) expect(screen.getByText(text)).toBeTruthy();
});

it('accepts at most four follow-ups of 4 to 90 characters and still rejects unknown fields', () => {
  expect(comparisonSpec.safeParse(shop()).success).toBe(true);
  expect(comparisonSpec.safeParse(shop({ actions: ['a', 'b', 'c', 'd', 'e'].map(x => x.repeat(8)) })).success).toBe(false);
  expect(comparisonSpec.safeParse(shop({ actions: ['no'] })).success).toBe(false);
  expect(comparisonSpec.safeParse(shop({ actions: ['x'.repeat(91)] })).success).toBe(false);
  expect(comparisonSpec.safeParse(shop({ actions: ['<b>bold</b> sentence'] })).success).toBe(false);
  expect(comparisonSpec.safeParse(two({ actions: ['Show the menu for Vanguard'], prompt: 'hidden' })).success).toBe(false);   // no second, hidden field
});
