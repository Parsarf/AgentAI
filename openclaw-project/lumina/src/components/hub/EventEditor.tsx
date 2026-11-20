import { useState } from 'react';
import { addresses, failed, hub, type HubAccount, type HubAction, type HubCalendar } from '../../lib/hub';

/** A new event, made by the customer's own hand (roadmap Phase 6, #61 and #D7): pressing Create is their approval, and it goes through the action pipeline once (one event even
 *  if the press is repeated), with Undo afterwards. Only calendars this account may change are offered. What will happen to other people is said before Create. */
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
  if (!writable.length) return <p className="muted small">None of your calendars can be changed from here yet.</p>;
  const invited = addresses(people);
  const next = (d: string) => { const t = new Date(d + 'T00:00:00Z'); t.setUTCDate(t.getUTCDate() + 1); return t.toISOString().slice(0, 10); };
  const create = async () => {
    const [connection, ...rest] = where.split('|'); const calendar = rest.join('|');
    setBusy(true); setErr('');
    try {
      const r = await hub.createEvent({ connection, calendar, title: title.trim(), start: allDay ? date : `${date}T${from}`, end: allDay ? next(date) : `${date}T${to}`, all_day: allDay || undefined,
        attendees: invited.length ? invited : undefined, place: place.trim() || undefined, description: notes.trim() || undefined, notify: invited.length ? notify : undefined });
      if (r.action.state === 'done' || r.action.state === 'approved' || r.action.state === 'executing') onDone(r.action);
      else setErr(r.action.ended_words || 'The event was not created.');
    } catch (e) { setErr(failed(e)); } finally { setBusy(false); }
  };
  const label = (c: HubCalendar) => `${c.name}${accounts.length > 1 ? ' · ' + (accounts.find(a => a.id === c.connection_id)?.identity ?? '') : ''}`;
  return (
    <form className="hub-event-editor" aria-label="New event" onSubmit={e => { e.preventDefault(); if (title.trim()) void create(); }}>
      <label>Title <input value={title} onChange={e => setTitle(e.target.value)} required maxLength={500} autoFocus /></label>
      <label>Calendar <select value={where} onChange={e => setWhere(e.target.value)}>{writable.map(c => <option key={c.connection_id + c.id} value={`${c.connection_id}|${c.id}`}>{label(c)}</option>)}</select></label>
      <label>Day <input type="date" value={date} onChange={e => setDate(e.target.value)} required /></label>
      <label className="row"><input type="checkbox" checked={allDay} onChange={e => setAllDay(e.target.checked)} /> All day</label>
      {!allDay && <div className="row"><label>From <input type="time" value={from} onChange={e => setFrom(e.target.value)} required /></label>
        <label>To <input type="time" value={to} onChange={e => setTo(e.target.value)} required /></label></div>}
      <label>People <input value={people} onChange={e => setPeople(e.target.value)} placeholder="Addresses, separated by commas" /></label>
      {!!invited.length && <label className="row"><input type="checkbox" checked={notify} onChange={e => setNotify(e.target.checked)} /> Send invitations</label>}
      <label>Place <input value={place} onChange={e => setPlace(e.target.value)} maxLength={500} /></label>
      <label>Notes <textarea value={notes} onChange={e => setNotes(e.target.value)} maxLength={8000} rows={3} /></label>
      {!!invited.length && <p className="small" role="status">{notify ? `${invited.length} ${invited.length === 1 ? 'person' : 'people'} will be invited by email.` : 'Nobody is told.'}</p>}
      {err && <p className="notice warning small" role="alert">{err}</p>}
      <div className="row"><button type="submit" className="btn" disabled={busy || !title.trim()}>Create</button><button type="button" className="btn ghost" onClick={onCancel} disabled={busy}>Cancel</button></div>
    </form>);
}
