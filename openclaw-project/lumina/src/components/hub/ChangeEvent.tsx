import { useState } from 'react';
import SeriesScope from './SeriesScope';
import Field from '../ui/Field';
import { addDays, addresses, failed, hub, localTime, type EventChange, type HubAccount, type HubAction, type HubEvent, type Scope } from '../../lib/hub';

const daysBetween = (a: string, b: string) => Math.round((Date.parse(b.slice(0, 10) + 'T00:00:00Z') - Date.parse(a.slice(0, 10) + 'T00:00:00Z')) / 86400000);

/** Changing an event with the customer's own hand (#62, #D7). Only what they edit is sent. Who is told is said before Save, and a repeating event waits until the customer
 *  says how much of the series the change is for (never guessed). Pressing Save is the approval; the result comes back with Undo. */
export default function ChangeEvent({ event, account, zone, onDone, onCancel }: {
  event: HubEvent; account: HubAccount; zone: string; onDone(action: HubAction, words: string): void; onCancel(): void;
}) {
  const startLocal = event.all_day ? (event.start_date ?? '') : localTime(event.start_epoch, zone);
  const endLocal = event.all_day ? (event.end_date ?? '') : localTime(event.end_epoch, zone);
  const span = daysBetween(startLocal, endLocal);
  const me = (event.attendees ?? []).find(a => a.self)?.address.toLowerCase();
  const invited = (event.attendees ?? []).filter(a => !a.self).map(a => a.address.toLowerCase());
  const [title, setTitle] = useState(event.title); const [date, setDate] = useState(startLocal.slice(0, 10));
  const [from, setFrom] = useState(event.all_day ? '' : startLocal.slice(11)); const [to, setTo] = useState(event.all_day ? '' : endLocal.slice(11));
  const [people, setPeople] = useState(invited.join(', ')); const [place, setPlace] = useState(event.place ?? ''); const [notes, setNotes] = useState(event.description ?? '');
  const [notify, setNotify] = useState(true); const [scope, setScope] = useState<Scope | null>(null); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');

  const after = addresses(people).map(a => a.toLowerCase()).filter(a => a !== me);
  const told = new Set([...invited, ...after]).size;
  const changes = (): Partial<EventChange> => {
    const out: Partial<EventChange> = {};
    if (title.trim() && title.trim() !== event.title) out.title = title.trim();
    const start = event.all_day ? date : `${date}T${from}`;
    const end = event.all_day ? addDays(date, span) : `${addDays(date, span)}T${to}`;
    if (start !== startLocal || end !== endLocal) Object.assign(out, { start, end }, event.all_day ? { all_day: true } : { timezone: zone });
    if ([...after].sort().join() !== [...invited].sort().join()) out.attendees = after;
    if (place.trim() !== (event.place ?? '')) out.place = place.trim();
    if (notes.trim() !== (event.description ?? '').trim()) out.description = notes.trim();
    return out;
  };
  const save = async () => {
    const fields = changes();
    if (!Object.keys(fields).length) { onCancel(); return; }
    if (event.series_id && !scope) { setErr('Choose which events this change is for.'); return; }
    setBusy(true); setErr('');
    try {
      const r = await hub.changeEvent({ connection: event.connection_id, calendar: event.calendar_id, event: event.id, series: event.series_id, scope: scope ?? undefined, ...fields, notify });
      if (r.action.state === 'done') onDone(r.action, `"${fields.title ?? event.title}" was changed.`);
      else setErr(r.action.ended_words || 'The event was not changed.');
    } catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  };
  const late = !event.all_day && !!from && !!to && span === 0 && to <= from ? 'It must end after it starts.' : '';
  return (
    <form className="form hub-change" aria-label="Change event" noValidate onSubmit={e => { e.preventDefault(); if (title.trim() && !late) void save(); }}>
      <p className="faint small">{account.identity}</p>
      <Field label="Title" note="Required" error={title.trim() ? '' : 'Give the event a title.'}>{p => <input {...p} className="input" value={title} onChange={e => setTitle(e.target.value)} required maxLength={500} />}</Field>
      <div className="field-row">
        <Field label="Date">{p => <input {...p} className="input" type="date" value={date} onChange={e => setDate(e.target.value)} required />}</Field>
        {!event.all_day && <Field label="Starts">{p => <input {...p} className="input" type="time" value={from} onChange={e => setFrom(e.target.value)} required aria-invalid={late ? true : undefined} />}</Field>}
        {!event.all_day && <Field label="Ends" error={late}>{p => <input {...p} className="input" type="time" value={to} onChange={e => setTo(e.target.value)} required />}</Field>}
      </div>
      <Field label="People">{p => <input {...p} className="input" value={people} onChange={e => setPeople(e.target.value)} placeholder="Email addresses, separated by commas" autoComplete="off" spellCheck={false} />}</Field>
      <Field label="Place">{p => <input {...p} className="input" value={place} onChange={e => setPlace(e.target.value)} maxLength={500} />}</Field>
      <Field label="Notes">{p => <textarea {...p} className="input" value={notes} onChange={e => setNotes(e.target.value)} maxLength={8000} rows={3} />}</Field>
      {event.series_id && <SeriesScope name={`change-${event.id}`} value={scope} onChange={setScope} legend="This event repeats. Which events should change?" />}
      {told > 0 && <label className="check-row"><input type="checkbox" checked={notify} onChange={e => setNotify(e.target.checked)} /> Tell the people invited</label>}
      {told > 0 && <p className="faint small" role="status">{notify ? `${told} ${told === 1 ? 'person is' : 'people are'} told about the change.` : 'Nobody is told.'}</p>}
      {err && <p className="notice warning small" role="alert">{err}</p>}
      <div className="form-actions"><button type="button" className="btn small tertiary" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="btn small primary" disabled={busy || !title.trim() || !!late || (!!event.series_id && !scope)}>Save</button></div>
    </form>);
}
