import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import AgentResponse from './response/AgentResponse';
import { Emojified } from './Emoji';

afterEach(cleanup);
const imgs = (root: ParentNode = document) => [...root.querySelectorAll('img.emoji')] as HTMLImageElement[];

// The reply from the bug report: a table card as a bare JSON paragraph whose heat column is a row of chili emoji.
const spicy = JSON.stringify({
  schemaVersion: '1.0', type: 'table', title: 'Complete Spicy Food Guide for Victorville, CA 92618',
  columns: [{ id: 'restaurant', label: 'Restaurant' }, { id: 'heat', label: 'Heat Level' }],
  rows: [{ restaurant: 'Spice of India', heat: '🌶️🌶️🌶️🌶️' }, { restaurant: 'Himalayan Indian Kitchen', heat: '🌶️🌶️🌶️' }], highlightRow: 0 });

describe('Emojified', () => {
  it('shows emoji as OpenMoji pictures that still carry the character as alt text', () => {
    const { container } = render(<p><Emojified text="Great 👍🏽 and 🇺🇸" /></p>);
    const pics = imgs(container);
    expect(pics.map(i => i.alt)).toEqual(['👍🏽', '🇺🇸']);
    expect(pics[0].getAttribute('src')).toMatch(/\/openmoji\/svg\/1F44D-1F3FD\.svg$/);
    expect(container.textContent).toBe('Great  and ');                // the pictures are images, not text; their alt text carries the characters
  });
});

describe('emoji in agent replies', () => {
  it('shows emoji in prose, bold text and lists as pictures', () => {
    render(<AgentResponse content={'Hot stuff 🔥 **very 🌶️ spicy**\n\n- first 😀\n- second'} />);
    expect(imgs().map(i => i.alt)).toEqual(['🔥', '🌶️', '😀']);
    expect(screen.getAllByRole('listitem').length).toBe(2);
  });

  it('keeps emoji literal inside code', () => {
    render(<AgentResponse content={'Use `print("😀")` or:\n\n```js\nconsole.log("🔥")\n```'} />);
    expect(imgs().length).toBe(0);
    expect(document.body.textContent).toContain('print("😀")');
    expect(document.body.textContent).toContain('console.log("🔥")');
  });

  it('does not hijack real Markdown images', () => {
    render(<AgentResponse content={'![A chart](https://example.com/chart.png) and 😀'} />);
    expect(imgs().map(i => i.alt)).toEqual(['😀']);
    expect(document.body.textContent).toContain('A chart');
    expect(screen.getByRole('link', { name: /View image/ }).getAttribute('href')).toBe('https://example.com/chart.png');
  });

  it('still turns the reported JSON into a registry table when it contains emoji, with pictures in its cells', async () => {
    const { container } = render(<AgentResponse content={'Here is the guide:\n\n' + spicy + '\n\nWant more?'} />);
    expect(await screen.findByRole('table')).toBeTruthy();
    expect(container.textContent).not.toContain('schemaVersion');           // no raw JSON
    const cells = [...container.querySelectorAll('td')];
    expect(imgs(cells[1]).length).toBe(4);                                 // 🌶️ x4 in the first row's heat cell
    expect(imgs(cells[3]).length).toBe(3);
    expect(cells[0].textContent).toContain('Spice of India');
  });

  it('leaves text without emoji exactly as before', () => {
    render(<AgentResponse content={'No pictures here: © 2026, 100% fine.'} />);
    expect(imgs().length).toBe(0);
    expect(document.body.textContent).toContain('No pictures here: © 2026, 100% fine.');
  });
});
