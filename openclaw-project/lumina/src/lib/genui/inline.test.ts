import { describe, expect, it } from 'vitest';
import { inlineCard } from './inline';

// The reply from the bug report, exactly as the assistant wrote it: no column types, as the server accepts and defaults them.
const reported = '{"schemaVersion":"1.0","type":"table","title":"Complete Spicy Food Guide for Victorville, CA 92618","columns":[{"id":"restaurant","label":"Restaurant"},{"id":"cuisine","label":"Cuisine Type"},{"id":"heat","label":"Heat Level"},{"id":"best_dish","label":"Best for Heat Lovers"}],"rows":[{"restaurant":"Spice of India","cuisine":"Indian","heat":"\ud83c\udf36\ufe0f\ud83c\udf36\ufe0f\ud83c\udf36\ufe0f\ud83c\udf36\ufe0f","best_dish":"Authentic curries (last authentic spot in high desert!)"}],"highlightRow":0}';

describe('inlineCard accepts what the server accepts', () => {
  it('turns the reported table JSON (columns without a type) into a table card, defaulting each column to text', () => {
    const card = inlineCard(reported);
    expect(card?.kind).toBe('table');
    if (card?.kind === 'table') { expect(card.spec.columns.every(c => c.type === 'text')).toBe(true); expect(card.spec.rows[0].heat).toBe('\u{1F336}\uFE0F'.repeat(4)); }
  });

  it('accepts a comparison whose items leave out facts, pros and cons', () => {
    const card = inlineCard(JSON.stringify({ schemaVersion: '1.0', type: 'comparison', title: 'Two options', items: [{ name: 'A' }, { name: 'B', price: '$5' }] }));
    expect(card?.kind).toBe('comparison');
    if (card?.kind === 'comparison') expect(card.spec.items.map(i => [i.facts, i.pros, i.cons])).toEqual([[[], [], []], [[], [], []]]);
  });

  it('still refuses specs the server would refuse, and ordinary JSON', () => {
    expect(inlineCard('{"schemaVersion":"1.0","type":"table","title":"x","columns":[{"id":"a","label":"A","type":"bogus"}],"rows":[{"a":"1"}]}')).toBeNull();
    expect(inlineCard('{"hello":"world"}')).toBeNull();
    expect(inlineCard('not json')).toBeNull();
  });
});
