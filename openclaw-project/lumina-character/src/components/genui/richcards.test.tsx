import { afterEach, beforeEach, expect, it, vi, describe } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { ChatActionsContext } from '../../lib/chatActions';
import { CARD_SCHEMAS } from '../../lib/genui/data';
import { inlineCard } from '../../lib/genui/inline';
import BlockView from './BlockView';
import { AnswerCard, CalloutCard, ChoiceCard, mapLink, PlacesCard, ProductsCard, SourcesCard, StepsCard, TimelineCard } from './RichCards';
import type { Block } from '../../lib/genui/schema';

afterEach(cleanup);
beforeEach(() => localStorage.clear());
const inChat = (send = vi.fn().mockResolvedValue(undefined)) => ({ send, wrap: (ui: React.ReactNode) => <ChatActionsContext.Provider value={{ send }}>{ui}</ChatActionsContext.Provider> });

const places = CARD_SCHEMAS.places.parse({
  schemaVersion: '1.0', type: 'places', title: 'Pizza near you', actions: ['Only places that deliver'],
  items: [
    { name: 'Luigi', address: '1 Main St', rating: 4.2, reviews: 812, price: '$$', distance: '0.4 mi', distance_km: 0.6, open: true, tags: ['wood-fired'], actions: ['Show the menu for Luigi'] },
    { name: 'Nonna', address: '9 Elm St', rating: 4.8, reviews: 15200, price: '$$$', distance: '1.2 mi', distance_km: 1.9, open: false },
    { name: 'Slice Bar', rating: 3.9, price: '$', distance_km: 0.2, open: true },
  ],
});

describe('places', () => {
  it('filters by open now and price in the browser, and says how many are shown', () => {
    render(<PlacesCard spec={places} />);
    expect(screen.getByText('3 places')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Open now' }));
    expect(screen.getByText('2 of 3')).toBeTruthy(); expect(screen.queryByText('Nonna')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '$' }));
    expect(screen.getByText('1 of 3')).toBeTruthy(); expect(screen.getByText('Slice Bar')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '$' })); fireEvent.click(screen.getByRole('button', { name: '$$$' }));
    expect(screen.getByText(/No places match/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Show all' }));
    expect(screen.getByText('3 places')).toBeTruthy();
  });

  it('sorts by rating or distance and shows ratings, review counts and open state', () => {
    render(<PlacesCard spec={places} />);
    const names = () => screen.getAllByRole('heading', { level: 4 }).map(h => h.textContent);
    expect(names()).toEqual(['Luigi', 'Nonna', 'Slice Bar']);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'rating' } }); expect(names()).toEqual(['Nonna', 'Luigi', 'Slice Bar']);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'distance' } }); expect(names()).toEqual(['Slice Bar', 'Luigi', 'Nonna']);
    expect(screen.getByText('(15k)')).toBeTruthy(); expect(screen.getByText('Closed')).toBeTruthy();
  });

  it('links each place to a map search that only opens when clicked, and sends a place\'s own follow-up', async () => {
    expect(mapLink('Luigi', '1 Main St')).toBe('https://www.google.com/maps/search/?api=1&query=Luigi%201%20Main%20St');
    const { send, wrap } = inChat();
    render(wrap(<PlacesCard spec={places} />));
    expect(screen.getAllByRole('link', { name: /Map/ }).length).toBe(3);
    fireEvent.click(screen.getByText('Show the menu for Luigi'));
    await screen.findByText('✓ Show the menu for Luigi');
    expect(send).toHaveBeenCalledWith('Show the menu for Luigi');
    expect(screen.getByText('Only places that deliver')).toBeTruthy();
  });
});

const products = CARD_SCHEMAS.products.parse({
  schemaVersion: '1.0', type: 'products', title: 'Paddles under $200',
  items: [
    { name: 'Vanguard', price: '$199', price_value: 199, store: 'Amazon', rating: 4.5, specs: [{ label: 'Weight', value: '8 oz' }] },
    { name: 'Gearbox', price: '$149', price_value: 149, store: 'Gearbox', rating: 4.7 },
    { name: 'Joola', price: '$99', price_value: 99, store: 'Amazon', rating: 4.1, badge: 'Best value' },
    { name: 'Selkirk', price: '$179', price_value: 179, store: 'Selkirk', rating: 4.6 },
  ],
});

describe('products', () => {
  it('sorts by price and rating and filters by store', () => {
    render(<ProductsCard spec={products} />);
    const names = () => screen.getAllByRole('heading', { level: 4 }).map(h => h.textContent);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'low' } }); expect(names()).toEqual(['Joola', 'Gearbox', 'Selkirk', 'Vanguard']);
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'high' } }); expect(names()[0]).toBe('Vanguard');
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'rating' } }); expect(names()[0]).toBe('Gearbox');
    fireEvent.click(screen.getByRole('button', { name: 'Amazon' }));
    expect(names().sort()).toEqual(['Joola', 'Vanguard']); expect(screen.getByText('2 of 4')).toBeTruthy();
  });

  it('lets the person tick up to three and sends exactly the compare sentence shown, once', async () => {
    const { send, wrap } = inChat();
    render(wrap(<ProductsCard spec={products} />));
    const boxes = screen.getAllByRole('checkbox');
    fireEvent.click(boxes[0]);
    expect(screen.queryByText(/^Compare /)).toBeNull();                                         // one ticked is not a comparison yet
    fireEvent.click(boxes[1]); fireEvent.click(boxes[2]);
    expect((boxes[3] as HTMLInputElement).disabled).toBe(true);                                 // at most three
    const go = screen.getByText('Compare Vanguard, Gearbox and Joola');
    fireEvent.click(go); fireEvent.click(go);
    await screen.findByText('✓ Compare Vanguard, Gearbox and Joola');
    expect(send).toHaveBeenCalledTimes(1); expect(send).toHaveBeenCalledWith('Compare Vanguard, Gearbox and Joola');
  });

  it('offers no ticking outside a chat', () => {
    render(<ProductsCard spec={products} />);
    expect(screen.queryByRole('checkbox')).toBeNull();
  });
});

describe('steps', () => {
  const steps = CARD_SCHEMAS.steps.parse({ schemaVersion: '1.0', type: 'steps', title: 'Set up the router', items: [{ title: 'Plug it in' }, { title: 'Open the app', detail: 'Use the QR code' }, { title: 'Pick a password' }] });
  it('ticks steps off, shows progress, and remembers it in this browser', () => {
    const first = render(<StepsCard spec={steps} />);
    expect(screen.getByText('0 of 3 done')).toBeTruthy();
    fireEvent.click(screen.getAllByRole('checkbox')[1]);
    expect(screen.getByText('1 of 3 done')).toBeTruthy(); expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('1');
    first.unmount();
    render(<StepsCard spec={steps} />);
    expect(screen.getByText('1 of 3 done')).toBeTruthy(); expect((screen.getAllByRole('checkbox')[1] as HTMLInputElement).checked).toBe(true);
  });
  it('still works when the browser will not store anything', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('private'); });
    render(<StepsCard spec={steps} />);
    fireEvent.click(screen.getAllByRole('checkbox')[0]);
    expect(screen.getByText('1 of 3 done')).toBeTruthy(); spy.mockRestore();
  });
});

describe('answer, callout, timeline, sources', () => {
  it('shows the result first, how sure it is, and where it came from', () => {
    const spec = CARD_SCHEMAS.answer.parse({ schemaVersion: '1.0', type: 'answer', title: 'Right now', value: '72°F', headline: 'It is sunny in Austin', confidence: 'uncertain',
      sources: [{ title: 'National Weather Service', site: 'weather.gov', link: 'https://weather.gov/' }], actions: ['What about tomorrow?'] });
    const { wrap } = inChat();
    render(wrap(<AnswerCard spec={spec} />));
    expect(screen.getByText('72°F')).toBeTruthy(); expect(screen.getByText('It is sunny in Austin')).toBeTruthy(); expect(screen.getByText('Not certain')).toBeTruthy();
    expect(screen.getByRole('link', { name: /weather\.gov/ }).getAttribute('href')).toBe('https://weather.gov/');
    expect(screen.getByText('What about tomorrow?')).toBeTruthy();
  });
  it('gives a warning callout an alert role and a tip a note role', () => {
    render(<><CalloutCard spec={CARD_SCHEMAS.callout.parse({ schemaVersion: '1.0', type: 'callout', tone: 'warning', text: 'Prices change often.' })} />
      <CalloutCard spec={CARD_SCHEMAS.callout.parse({ schemaVersion: '1.0', type: 'callout', tone: 'tip', title: 'Tip', text: 'Book before 6pm.' })} /></>);
    expect(screen.getByRole('alert').textContent).toContain('Prices change often.'); expect(screen.getByRole('note').textContent).toContain('Book before 6pm.');
  });
  it('lays out a timeline and a source list', () => {
    render(<><TimelineCard spec={CARD_SCHEMAS.timeline.parse({ schemaVersion: '1.0', type: 'timeline', title: 'Trip', items: [{ when: 'Day 1', title: 'Arrive' }, { when: 'Day 2', title: 'Museum', detail: 'Book ahead' }] })} />
      <SourcesCard spec={CARD_SCHEMAS.sources.parse({ schemaVersion: '1.0', type: 'sources', items: [{ title: 'Guide', link: 'https://guide.example/', site: 'guide.example' }] })} /></>);
    expect(screen.getByText('Day 2')).toBeTruthy(); expect(screen.getByText('Book ahead')).toBeTruthy(); expect(screen.getByRole('heading', { name: 'Sources' })).toBeTruthy();
  });
});

describe('choice', () => {
  const single = CARD_SCHEMAS.choice.parse({ schemaVersion: '1.0', type: 'choice', question: 'Which size?', options: ['Small', 'Medium', 'Large'] });
  const many = CARD_SCHEMAS.choice.parse({ schemaVersion: '1.0', type: 'choice', question: 'Which toppings?', options: ['Cheese', 'Mushrooms', 'Olives'], multiple: true });
  it('sends the pressed option exactly, once, and then locks the others', async () => {
    const { send, wrap } = inChat();
    render(wrap(<ChoiceCard spec={single} />));
    fireEvent.click(screen.getByText('Medium')); fireEvent.click(screen.getByText('Large'));
    await screen.findByText('✓ Medium');
    expect(send).toHaveBeenCalledTimes(1); expect(send).toHaveBeenCalledWith('Medium');
    expect((screen.getByText('Large') as HTMLButtonElement).disabled).toBe(true);
  });
  it('lets several be ticked and sends them together in the words shown', async () => {
    const { send, wrap } = inChat();
    render(wrap(<ChoiceCard spec={many} />));
    fireEvent.click(screen.getByRole('button', { name: 'Cheese' })); fireEvent.click(screen.getByRole('button', { name: 'Olives' }));
    fireEvent.click(screen.getByText('Send: Cheese and Olives'));
    await screen.findByText('✓ Send: Cheese and Olives');
    expect(send).toHaveBeenCalledWith('Cheese and Olives');
  });
  it('cannot send anything outside a chat', () => {
    render(<ChoiceCard spec={single} />);
    expect((screen.getByText('Small') as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('schemas and wiring', () => {
  it('accepts each new kind inline and refuses unknown kinds and unknown fields', () => {
    expect(inlineCard(JSON.stringify(places))?.kind).toBe('places');
    expect(inlineCard(JSON.stringify(products))?.kind).toBe('products');
    expect(inlineCard(JSON.stringify({ schemaVersion: '1.0', type: 'html', body: '<script>' }))).toBeNull();
    expect(inlineCard(JSON.stringify({ ...places, onclick: 'x' }))).toBeNull();
    expect(inlineCard(JSON.stringify({ schemaVersion: '1.0', type: 'display', style: 'steps' }))).toBeNull();          // a display hint is never a card the assistant can write
    expect(CARD_SCHEMAS.places.safeParse({ ...places, items: [{ name: 'X', rating: 7 }] }).success).toBe(false);
    expect(CARD_SCHEMAS.choice.safeParse({ schemaVersion: '1.0', type: 'choice', question: 'q?', options: ['only one'] }).success).toBe(false);
    expect(CARD_SCHEMAS.places.safeParse({ ...places, items: [{ name: 'X', link: 'javascript:alert(1)' }] }).success).toBe(false);
  });
  it('draws a stored block of a new kind, and draws nothing for a display hint', () => {
    const block = (kind: string, spec: unknown): Block => ({ id: kind, conversation_id: 'c', anchor_message_id: 1, kind: kind as Block['kind'], schema_version: '1.0', spec, state: {}, version: 1, status: 'final', launched_request_id: null, created_epoch: 1, updated_epoch: 1 } as unknown as Block);
    const { container } = render(<><BlockView block={block('places', places)} onChanged={() => {}} /><BlockView block={block('display', { style: 'steps' })} onChanged={() => {}} /></>);
    expect(within(container).getByText('Pizza near you')).toBeTruthy();
    expect(container.textContent).not.toContain('can’t be shown');
  });
});
