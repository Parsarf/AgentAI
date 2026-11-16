import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import * as I from '../Icons';
import Sheet from '../ui/Sheet';
import { api } from '../../lib/api';
import { chatTitle, sortRecent } from '../../lib/chats';
import { forPlace, keyWords, placeOf, presses, shortcut, SHORTCUTS } from '../../lib/shortcuts';
import { useData } from '../../state/data';
import { useSettings } from '../../state/settings';
import { useAssistant } from './Assistant';
import { useFrame } from './FrameProvider';
import { available } from './Nav';

/** Something to do (not to open): it runs, and is shown apart from things to open, with its shortcut. */
export interface Command { id: string; label: string; run(): void; shortcut?: string; group?: string }
interface Commands { page: Command[]; setPage(c: Command[]): void; open: boolean; setOpen(v: boolean): void; help: boolean; setHelp(v: boolean): void }
const Ctx = createContext<Commands | null>(null);

export function CommandsProvider({ children }: { children: ReactNode }) {
  const [page, setPageState] = useState<Command[]>([]); const [open, setOpen] = useState(false); const [help, setHelp] = useState(false);
  const setPage = useCallback((c: Command[]) => setPageState(c), []);
  const value = useMemo(() => ({ page, setPage, open, setOpen, help, setHelp }), [page, setPage, open, help]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
export const useCommandBar = () => useContext(Ctx);

/** A page offers its own commands while it is open ("go to next week", "new folder"). Each must also be reachable on the page by pointer. */
export function useCommands(commands: Command[]) {
  const c = useContext(Ctx); const ref = useRef(commands); ref.current = commands;
  const key = commands.map(x => x.id + x.label).join('|');
  useEffect(() => { c?.setPage(ref.current.map(x => ({ ...x, run: () => ref.current.find(y => y.id === x.id)?.run() }))); }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => () => c?.setPage([]), []);   // eslint-disable-line react-hooks/exhaustive-deps
}

type Found = { kind: 'chat' | 'task' | 'file' | 'mail' | 'event'; id: string; title: string; detail?: string; source?: string; connection?: string; calendar?: string; conversation_id?: string | null };
interface Row { key: string; label: string; detail?: string; group: string; act: 'open' | 'do'; keys?: string; run(): void }
const KIND_GROUP: Record<Found['kind'], string> = { chat: 'Chats', task: 'Tasks', file: 'Files', mail: 'Mail', event: 'Events' };
const DROPPED: Record<string, string> = { chats: 'chats', tasks: 'tasks', files: 'files', mail: 'mail', events: 'events' };
const SETTINGS = [{ id: 'usage', label: 'Usage and spending' }, { id: 'access', label: 'Access and connected accounts' }, { id: 'integrations', label: 'Integrations' }, { id: 'memory', label: 'Memory' },
  { id: 'data', label: 'Your data' }, { id: 'appearance', label: 'Appearance and density' }, { id: 'model', label: 'Your own model' }, { id: 'browser', label: 'Your browser' }];
const RECENT_KEY = 'lumina.recent';
const readRecent = (): { to: string; label: string }[] => { try { return JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]'); } catch { return []; } };
export function remember(to: string, label: string) { try { localStorage.setItem(RECENT_KEY, JSON.stringify([{ to, label }, ...readRecent().filter(r => r.to !== to)].slice(0, 6))); } catch { /* private mode */ } }

/** The command bar (Ctrl/Cmd+K, or /): recent things and the actions that fit the page when empty; typing searches chats, tasks, files, mail, events and settings
 *  through one server route, with places and actions found here. Things to open and things to do are listed apart. Never the only way to anything. */
export function CommandBar({ onClose }: { onClose(): void }) {
  const { app, chats } = useData(); const nav = useNavigate(); const { pathname } = useLocation(); const frame = useFrame(); const assistant = useAssistant();
  const c = useCommandBar()!; const { compact, setCompact, reducedMotion, setReducedMotion } = useSettings();
  const [q, setQ] = useState(''); const [i, setI] = useState(0); const [found, setFound] = useState<{ q: string; results: Found[]; dropped: string[] } | null>(null); const [searching, setSearching] = useState(false);
  const input = useRef<HTMLInputElement>(null); const list = useRef<HTMLUListElement>(null);
  useEffect(() => input.current?.focus(), []);
  const term = q.trim(); const low = term.toLowerCase();
  useEffect(() => {
    if (!term) { setFound(null); return; }
    let stop = false; setSearching(true);
    const t = window.setTimeout(() => {
      api<{ results: Found[]; dropped: string[] }>('GET', `/v1/search?q=${encodeURIComponent(term)}`)
        .then(r => { if (!stop) setFound({ q: term, results: r.results, dropped: r.dropped }); })
        .catch(() => { if (!stop) setFound({ q: term, results: [], dropped: ['everything'] }); })
        .finally(() => { if (!stop) setSearching(false); });
    }, 120);
    return () => { stop = true; window.clearTimeout(t); };
  }, [term]);

  const go = (to: string, label?: string) => { if (label) remember(to, label); void nav(to); onClose(); };
  const place = placeOf(pathname);
  const actions: Command[] = [
    ...c.page,
    { id: 'new-chat', label: 'New chat', run: () => go('/chat') },
    ...(frame?.declared.assistant ? [{ id: 'assistant', label: frame.placement.docked.assistant || frame.sheet === 'assistant' ? 'Close the assistant' : 'Open the assistant', shortcut: 'assistant', run: () => { onClose(); frame.toggle('assistant'); } }] : []),
    ...(frame?.declared.context ? [{ id: 'context', label: 'Show or hide the side column', shortcut: 'context', run: () => { onClose(); frame.toggle('context'); } }] : []),
    { id: 'density', label: compact ? 'Turn off compact (comfortable spacing)' : 'Turn on compact', shortcut: 'density', run: () => { setCompact(!compact); onClose(); } },
    { id: 'motion', label: reducedMotion ? 'Turn animations on' : 'Reduce motion', run: () => { setReducedMotion(!reducedMotion); onClose(); } },
    ...(app?.features.dashboard ? [{ id: 'connect', label: 'Connect a mail and calendar account', run: () => go('/settings?tab=access') }] : []),
    { id: 'help', label: 'Keyboard shortcuts', shortcut: 'help', run: () => { onClose(); c.setHelp(true); } },
  ];
  const places = available(app);
  const rows: Row[] = useMemo(() => {
    const out: Row[] = [];
    const match = (s: string) => !low || s.toLowerCase().includes(low);
    if (!low) {
      const recent = readRecent().slice(0, 4).map(r => ({ key: 'r' + r.to, label: r.label, group: 'Recent', act: 'open' as const, run: () => go(r.to, r.label) }));
      const recentChats = sortRecent(chats).slice(0, recent.length ? 3 : 5).map(ch => ({ key: 'c' + ch.id, label: chatTitle(ch), detail: 'Chat', group: 'Recent', act: 'open' as const, run: () => go(`/chat/${ch.id}`, chatTitle(ch)) }));
      out.push(...recent, ...recentChats.filter(r => !recent.some(x => x.label === r.label)));
    }
    out.push(...actions.filter(a => match(a.label)).map(a => ({ key: 'a' + a.id, label: a.label, group: 'Actions', act: 'do' as const, keys: a.shortcut ? shortcut(a.shortcut)?.keys : undefined, run: a.run })));
    out.push(...places.filter(p => match(p.label)).map(p => ({ key: 'p' + p.to, label: p.label, detail: 'Go to', group: 'Places', act: 'open' as const, keys: shortcut(`go-${p.to.slice(1)}`)?.keys, run: () => go(p.to) })));
    if (low) out.push(...SETTINGS.filter(s => match(s.label)).map(s => ({ key: 's' + s.id, label: s.label, detail: 'Settings', group: 'Settings', act: 'open' as const, run: () => go(`/settings/${s.id}`, s.label) })));
    for (const r of found && found.q === term ? found.results : []) {
      const to = r.kind === 'chat' ? `/chat/${r.id}` : r.kind === 'task' ? `/activity/${r.id}` : r.kind === 'file' ? `/files?open=${encodeURIComponent(`${r.source}:${r.id}`)}`
        : r.kind === 'mail' ? `/inbox?connection=${encodeURIComponent(r.connection ?? '')}&thread=${encodeURIComponent(r.id)}`
        : `/calendar?connection=${encodeURIComponent(r.connection ?? '')}&calendar=${encodeURIComponent(r.calendar ?? '')}&event=${encodeURIComponent(r.id)}`;
      out.push({ key: r.kind + r.id, label: r.title, detail: r.detail, group: KIND_GROUP[r.kind], act: 'open', run: () => go(to, r.title) });
    }
    return out;
  }, [low, found, chats, actions.map(a => a.label).join(), places.length]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setI(0); }, [low, found]);
  useEffect(() => { list.current?.querySelector('[aria-selected="true"]')?.scrollIntoView?.({ block: 'nearest' }); }, [i]);
  const groups = [...new Set(rows.map(r => r.group))];
  const ask = () => { onClose(); if (frame?.declared.assistant && assistant) { frame.reveal('assistant'); void assistant.send(term); } else void nav(`/chat?q=${encodeURIComponent(term)}`); };
  const dropped = found?.q === term ? found.dropped : [];

  return (
    <div className="cmd-back" onMouseDown={onClose} role="presentation">
      <div className="cmd" role="dialog" aria-modal="true" aria-label="Search and commands" onMouseDown={e => e.stopPropagation()}>
        <div className="cmd-input"><I.Search width={18} height={18} aria-hidden="true" />
          <input ref={input} value={q} placeholder={`Search, or type a command · ${place === 'chat' ? 'chats, mail, files' : 'anything'}`} aria-label="Search and commands" role="combobox" aria-expanded="true" aria-controls="cmd-list"
            aria-activedescendant={rows[i] ? `cmd-${i}` : undefined}
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Escape') { e.preventDefault(); onClose(); }
              else if (e.key === 'ArrowDown') { e.preventDefault(); setI(x => Math.min(x + 1, rows.length - 1)); }
              else if (e.key === 'ArrowUp') { e.preventDefault(); setI(x => Math.max(x - 1, 0)); }
              else if (e.key === 'Enter') { e.preventDefault(); if (rows[i]) rows[i].run(); else if (term) ask(); }
            }} />
          {searching && <span className="faint small" role="status">Searching…</span>}</div>
        <ul id="cmd-list" ref={list} role="listbox" aria-label="Results">
          {groups.map(g => <li key={g} role="presentation"><div className="cmd-group" role="presentation">{g}</div>
            <ul role="group" aria-label={g}>{rows.map((r, n) => r.group !== g ? null : <li key={r.key} id={`cmd-${n}`} role="option" aria-selected={n === i} className={`cmd-row ${r.act}`}
              onMouseMove={() => setI(n)} onClick={() => r.run()}>
              <span className="cmd-mark" aria-hidden="true">{r.act === 'do' ? <I.Bolt width={14} height={14} /> : <I.Chevron width={14} height={14} />}</span>
              <span className="cmd-label">{r.label}</span>{r.detail && <span className="faint small cmd-detail">{r.detail}</span>}
              {r.keys && <kbd className="kbd">{keyWords(r.keys)}</kbd>}</li>)}</ul></li>)}
        </ul>
        {term && !searching && found?.q === term && !rows.length && <div className="cmd-none" role="status"><p>Nothing matches “{term}”.</p>
          <button type="button" className="btn small" onClick={ask}><I.Spark width={14} height={14} /> Ask your assistant: “{term.length > 40 ? term.slice(0, 40) + '…' : term}”</button></div>}
        {dropped.length > 0 && <p className="cmd-dropped faint small" role="status">{dropped[0] === 'everything' ? 'Search did not answer just now: only places and actions are shown.' : `Could not search your ${dropped.map(d => DROPPED[d] ?? d).join(' and ')} just now.`}</p>}
        <p className="cmd-foot faint small"><kbd className="kbd">↑</kbd> <kbd className="kbd">↓</kbd> move · <kbd className="kbd">Enter</kbd> open · <kbd className="kbd">Esc</kbd> close · <kbd className="kbd">?</kbd> all shortcuts</p>
      </div>
    </div>);
}

/** Every shortcut for the current page, grouped, read from the one registry. */
export function HelpSheet({ onClose }: { onClose(): void }) {
  const { pathname } = useLocation(); const mine = forPlace(placeOf(pathname));
  const groups = [...new Set(mine.map(s => s.group))];
  return <Sheet title="Keyboard shortcuts" onClose={onClose} className="help-sheet">
    <p className="faint small">Everything here can also be done with the pointer.</p>
    {groups.map(g => <section key={g} aria-label={g} className="help-group"><h3 className="ci-h">{g}</h3>
      <dl>{mine.filter(s => s.group === g).map(s => <div key={s.id} className="help-row"><dt>{s.name}</dt><dd><kbd className="kbd">{keyWords(s.keys)}</kbd></dd></div>)}</dl></section>)}
  </Sheet>;
}

const typing = (t: EventTarget | null) => { const el = t as HTMLElement | null; return !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable); };

/** The frame's own shortcuts, from the registry: the command bar, help, zones, density, and "g then a letter" to move between places. */
export function useFrameKeys() {
  const frame = useFrame(); const c = useCommandBar(); const nav = useNavigate(); const { pathname } = useLocation(); const { compact, setCompact } = useSettings(); const { app } = useData();
  const pending = useRef<number>(0);
  useEffect(() => {
    const zones = () => ['.rail-nav, .bottom-bar', '.zone-context', '.zone-canvas', '.zone-inspector', '.zone-assistant'].map(s => document.querySelector<HTMLElement>(s)).filter((z): z is HTMLElement => !!z);
    const on = (e: KeyboardEvent) => {
      if (!frame || !c) return;
      const k = (id: string) => presses(e, shortcut(id)!.keys);
      if (k('command')) { e.preventDefault(); c.setOpen(true); return; }
      if (k('context')) { e.preventDefault(); frame.toggle('context'); return; }
      if (k('assistant') && frame.declared.assistant) { e.preventDefault(); frame.toggle('assistant'); return; }
      if (k('zone-next') || k('zone-prev')) {
        e.preventDefault(); const list = zones(); const at = list.findIndex(z => z.contains(document.activeElement));
        const to = list[(at + (k('zone-prev') ? -1 : 1) + list.length) % list.length];
        (to?.querySelector<HTMLElement>('a, button, input, [tabindex="0"]') ?? to)?.focus(); return;
      }
      if (typing(e.target) || document.querySelector('[aria-modal="true"]')) return;
      if (k('help')) { e.preventDefault(); c.setHelp(true); return; }
      if (k('command-slash') && placeOf(pathname) !== 'inbox') { e.preventDefault(); c.setOpen(true); return; }
      if (k('density')) { e.preventDefault(); setCompact(!compact); return; }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === 'g') { pending.current = Date.now(); return; }
      if (pending.current && Date.now() - pending.current < 1200) {
        pending.current = 0;
        const hit = SHORTCUTS.find(s => s.keys === `g ${e.key.toLowerCase()}`);
        const to = hit && available(app).find(p => `go-${p.to.slice(1)}` === hit.id);
        if (to) { e.preventDefault(); void nav(to.to); }
      }
    };
    window.addEventListener('keydown', on); return () => window.removeEventListener('keydown', on);
  }, [frame, c, nav, pathname, compact, setCompact, app]);
}
