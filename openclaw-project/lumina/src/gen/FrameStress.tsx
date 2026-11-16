import { useState } from 'react';
import { useParams } from 'react-router-dom';
import Workspace from '../components/frame/Workspace';
import List from '../components/frame/List';
import { EmptyState, Inspector, Table } from '../components/frame/parts';

/** The frame's stress test (UI remodel 1.2, after Linear's method): throwaway pages of every page type, filled with synthetic content, to prove the frame holds all of
 *  them at every width without a page-specific exception. Reached at /app/frame-stress/<kind>; not linked from anywhere. */
const KINDS = ['thread', 'list', 'calendar', 'files', 'settings', 'dashboard', 'table'] as const;
const words = (n: number) => Array.from({ length: n }, (_, i) => ['alpha', 'quarterly', 'review', 'thread', 'calendar', 'a-very-long-unbroken-token-that-should-wrap-or-ellipsize'][i % 6]).join(' ');
const rows = Array.from({ length: 100000 }, (_, i) => ({ id: String(i), name: `Item ${i} ${words(4)}`, kind: ['Task', 'Plan', 'Question'][i % 3], when: 1700000000 - i * 3600 }));

export default function FrameStress() {
  const { kind = 'thread' } = useParams(); const [open, setOpen] = useState<string | null>('3');
  const context = <nav aria-label="Stress context" className="stress-col">{Array.from({ length: 40 }, (_, i) => <a key={i} href="#" className="chatitem"><span className="ct">Context entry {i} {words(3)}</span></a>)}</nav>;
  const inspector = open ? <Inspector title={`Item ${open}: ${words(8)}`} meta="Synthetic">{<p>{words(120)}</p>}</Inspector> : null;
  const tools = <><button className="btn small">Action</button><button className="btn small primary">Primary</button></>;
  const pick = KINDS.includes(kind as typeof KINDS[number]) ? kind : 'thread';
  if (pick === 'thread') return <Workspace title={`Thread ${words(10)}`} tools={tools} context={context} contextLabel="Chats" inspector={inspector} inspectorKind="panel">
    <div className="thread" style={{ maxWidth: 860, margin: '0 auto' }}>{Array.from({ length: 30 }, (_, i) => <div key={i} className={`bubble ${i % 2 ? 'agent' : 'you'}`}>{words(i % 2 ? 80 : 12)}</div>)}</div></Workspace>;
  if (pick === 'list') return <Workspace title="Inbox" tools={tools} context={context} contextLabel="Mailboxes" inspector={inspector} onInspectorClose={() => setOpen(null)} fill>
    <div className="wsp-body"><List label="Rows" items={rows} rowHeight={64} rowKey={r => r.id} renderRow={r => <button type="button" className="stress-row" onClick={() => setOpen(r.id)}><b>{r.name}</b><span className="faint">{words(12)}</span></button>} /></div></Workspace>;
  if (pick === 'calendar') return <Workspace title="Calendar" tools={tools} context={context} contextLabel="Calendars" inspector={inspector} onInspectorClose={() => setOpen(null)} fill>
    <div className="wsp-body"><div className="stress-grid">{Array.from({ length: 7 * 24 }, (_, i) => <div key={i} className="stress-cell">{i % 7 === 0 ? `${i / 7}:00` : ''}</div>)}</div></div></Workspace>;
  if (pick === 'files') return <Workspace title="Files" tools={tools} context={context} contextLabel="Folders" inspector={inspector} onInspectorClose={() => setOpen(null)}>
    <div className="stress-tiles">{rows.slice(0, 60).map(r => <button key={r.id} type="button" className="panel card stress-tile" onClick={() => setOpen(r.id)}>{r.name}</button>)}</div></Workspace>;
  if (pick === 'settings') return <Workspace title="Settings" context={context} contextLabel="Sections">
    <div className="center" style={{ display: 'grid', gap: 16 }}>{Array.from({ length: 8 }, (_, i) => <section key={i} className="panel card"><h2>Section {i}</h2><p className="muted">{words(30)}</p><input className="input" aria-label={`Field ${i}`} defaultValue={words(5)} /></section>)}</div></Workspace>;
  if (pick === 'dashboard') return <Workspace title="Home" backdrop>
    <div className="center"><h1 className="hero">Good evening</h1><div className="caps">{Array.from({ length: 8 }, (_, i) => <section key={i} className="panel card"><h2>Tile {i}</h2><p className="muted">{words(20)}</p></section>)}</div>
      <EmptyState title="Nothing today">A plain sentence and a way forward.</EmptyState></div></Workspace>;
  return <Workspace title="Activity" tools={tools} context={context} contextLabel="Filters" inspector={inspector} onInspectorClose={() => setOpen(null)}>
    <Table label="Everything" rows={rows.slice(0, 400)} rowKey={r => r.id} selected={open} onOpen={r => setOpen(r.id)} columns={[{ key: 'name', label: 'What', render: r => r.name, sort: r => r.name },
      { key: 'kind', label: 'Kind', render: r => r.kind, sort: r => r.kind }, { key: 'when', label: 'When', render: r => new Date(r.when * 1000).toLocaleString(), sort: r => r.when }]} /></Workspace>;
}
