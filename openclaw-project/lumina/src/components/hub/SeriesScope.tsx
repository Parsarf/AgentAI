import type { Scope } from '../../lib/hub';

const WORDS: Record<Scope, string> = { this: 'This event', following: 'This and following events', all: 'All events' };

/** Which part of a repeating series a change touches (#62). Nothing is chosen for the customer: the change waits until they pick. */
export default function SeriesScope({ value, onChange, name, legend = 'Which events?', choices = ['this', 'following', 'all'] }: {
  value: Scope | null; onChange(scope: Scope): void; name: string; legend?: string; choices?: Scope[];
}) {
  return (
    <fieldset className="hub-scope">
      <legend className="small">{legend}</legend>
      {choices.map(s => <label key={s} className="row small"><input type="radio" name={name} checked={value === s} onChange={() => onChange(s)} /> {WORDS[s]}</label>)}
    </fieldset>);
}
