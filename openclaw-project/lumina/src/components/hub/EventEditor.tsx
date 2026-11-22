import { useRef, useState } from 'react';
import Sheet from '../ui/Sheet';
import Field from '../ui/Field';
import AllowChanges from './AllowChanges';
import { addresses, failed, hub, type HubAccount, type HubAction, type HubCalendar } from '../../lib/hub';

const ADDRESS = /^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$/;

/** A new event, made by the customer's own hand (roadmap Phase 6, #61 and #D7): pressing Create is their approval, and it goes through the action pipeline once (one event even
 *  if the press is repeated), with Undo afterwards. Only calendars this account may change are offered. What will happen to other people is said before Create.
 *  It is a dialog over the calendar: the grid behind it stays where the customer had it. The title comes first and has the focus; what is wrong is said under the field it
 *  is about; Esc, the close button and Cancel all leave without creating, and the focus goes back to what opened it. */
export default function EventEditor({ accounts, calendars, day, onDone, onCancel, initial }: {
  accounts: HubAccount[]; calendars: HubCalendar[]; day: string; onDone(action: HubAction): void; onCancel(): void;
  /** A time the customer picked from the assistant's suggestions (#65): its account, title, people and time are filled in; the customer still presses Create. */
  initial?: { connection: string; title: string; start: string; end: string; attendees: string[] };
}) {
  const writable = calendars.filter(c => (c.access === 'owner' || c.access === 'write') && accounts.some(a => a.id === c.connection_id && a.capabilities.event_write));
  const first = (initial && (writable.find(c => c.connection_id === initial.connection && c.primary) ?? writable.find(c => c.connection_id === initial.connection))) ?? writable.find(c => c.primary) ?? writable[0];
  const [where, setWhere] = useState(first ? `${first.connection_id}|${first.id}` : '');
  const [title, setTitle] = useState(initial?.title ?? ''); const [date, setDate] = useState(initial?.start.slice(0, 10) ?? day); const [allDay, setAllDay] = useState(false);
  const [from, setFrom] = useState(initial?.start.slice(11, 16) ?? '09:00'); const [to, setTo] = useState(initial?.end.slice(11, 16) ?? '10:00');
  const [people, setPeople] = useState(initial?.attendees.join(', ') ?? ''); const [place, setPlace] = useState('');
  const [notes, setNotes] = useState(''); const [notify, setNotify] = useState(true); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  const [tried, setTried] = useState(false); const form = useRef<HTMLDivElement>(null);

  if (!writable.length) return (
    <Sheet side="center" title="New event" onClose={onCancel}>
      <p className="muted">None of your calendars can be changed from here yet.</p>
      {accounts.filter(a => a.capabilities.missing?.event_write).map(a => <AllowChanges key={a.id} account={a} capability="event_write" />)}
    </Sheet>);

  const invited = addresses(people); const wrong = invited.filter(a => !ADDRESS.test(a));
  // What stops the event from being created, by the field it is about. The times are checked as they are typed; the rest once Create was pressed.
  const problems = {
    title: title.trim() ? '' : 'Give the event a title.',
    date: date ? '' : 'Choose a day.',
    time: allDay ? '' : !from || !to ? 'Choose when it starts and ends.' : to <= from ? 'It must end after it starts.' : '',
    people: wrong.length ? `“${wrong[0]}” is not an email address.` : '',
  };
  const shown = { title: tried ? problems.title : '', date: tried ? problems.date : '', time: problems.time, people: tried ? problems.people : '' };
  const next = (d: string) => { const t = new Date(d + 'T00:00:00Z'); t.setUTCDate(t.getUTCDate() + 1); return t.toISOString().slice(0, 10); };
  const create = async () => {
    if (busy) return;
    if (Object.values(problems).some(Boolean)) {
      setTried(true);
      window.setTimeout(() => form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(), 0);   // the first field that needs the customer
      return;
    }
    const [connection, ...rest] = where.split('|'); const calendar = rest.join('|');
    setBusy(true); setErr('');
    try {
      const r = await hub.createEvent({ connection, calendar, title: title.trim(), start: allDay ? date : `${date}T${from}`, end: allDay ? next(date) : `${date}T${to}`, all_day: allDay || undefined,
        attendees: invited.length ? invited : undefined, place: place.trim() || undefined, description: notes.trim() || undefined, notify: invited.length ? notify : undefined });
      if (r.action.state === 'done' || r.action.state === 'approved' || r.action.state === 'executing') onDone(r.action);
      else setErr(r.action.ended_words || 'The event was not created.');
    } catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  };

  // The calendar is named by its own name. With several accounts the list is grouped by account, and the account of the chosen calendar is said under the field
  // (unless the calendar is simply named after its account), so a long address never crowds the name out.
  const owners = accounts.filter(a => writable.some(c => c.connection_id === a.id));
  const chosen = writable.find(c => `${c.connection_id}|${c.id}` === where); const owner = owners.find(a => a.id === chosen?.connection_id);
  const option = (c: HubCalendar) => <option key={c.connection_id + c.id} value={`${c.connection_id}|${c.id}`}>{c.name}</option>;
  const told = !invited.length ? '' : notify ? `${invited.length} ${invited.length === 1 ? 'person' : 'people'} will be invited by email.` : 'Nobody is told.';

  return (
    <Sheet side="center" title="New event" onClose={() => { if (!busy) onCancel(); }} onSubmit={create} className="event-dialog"
      footer={<div className="form-actions">
        <p className="form-status" role="status">{told}</p>
        <button type="button" className="btn tertiary" onClick={onCancel} disabled={busy}>Cancel</button>
        <button type="submit" className="btn primary" disabled={busy} aria-busy={busy || undefined}>Create event</button></div>}>
      <div className="form" ref={form}>
        <Field label="Title" note="Required" error={shown.title}>{p =>
          <input {...p} className="input event-title" value={title} onChange={e => setTitle(e.target.value)} required maxLength={500} placeholder="Add a title" autoComplete="off" />}</Field>
        <fieldset className="field-group">
          <legend className="sr">When, and in which calendar</legend>
          <Field label="Calendar" hint={owners.length > 1 && owner && chosen && chosen.name !== owner.identity ? `In ${owner.identity}` : undefined}>{p =>
            <div className={`event-calendar cal-${chosen?.colour ?? 'grey'}`}><i className="event-calendar-dot" aria-hidden="true" />
              <select {...p} className="input" value={where} onChange={e => setWhere(e.target.value)}>
                {owners.length > 1 ? owners.map(a => <optgroup key={a.id} label={a.identity}>{writable.filter(c => c.connection_id === a.id).map(option)}</optgroup>) : writable.map(option)}</select></div>}</Field>
          <div className="field-row">
            <Field label="Date" error={shown.date}>{p => <input {...p} className="input" type="date" value={date} onChange={e => setDate(e.target.value)} required />}</Field>
            {!allDay && <Field label="Starts">{p => <input {...p} className="input" type="time" value={from} onChange={e => setFrom(e.target.value)} required aria-invalid={shown.time ? true : undefined} />}</Field>}
            {!allDay && <Field label="Ends" error={shown.time}>{p => <input {...p} className="input" type="time" value={to} onChange={e => setTo(e.target.value)} required />}</Field>}
          </div>
          <label className="check-row"><input type="checkbox" checked={allDay} onChange={e => setAllDay(e.target.checked)} /> All day</label>
        </fieldset>
        <Field label="People" error={shown.people}>{p =>
          <input {...p} className="input" value={people} onChange={e => setPeople(e.target.value)} placeholder="Email addresses, separated by commas" autoComplete="off" spellCheck={false} />}</Field>
        {!!invited.length && <label className="check-row"><input type="checkbox" checked={notify} onChange={e => setNotify(e.target.checked)} /> Send invitations</label>}
        <Field label="Place">{p => <input {...p} className="input" value={place} onChange={e => setPlace(e.target.value)} maxLength={500} autoComplete="off" />}</Field>
        <Field label="Notes">{p => <textarea {...p} className="input" value={notes} onChange={e => setNotes(e.target.value)} maxLength={8000} rows={3} />}</Field>
        {err && <p className="notice warning small" role="alert">{err}</p>}
      </div>
    </Sheet>);
}
