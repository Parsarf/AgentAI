import { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api } from '../lib/api';
import { isActive } from '../lib/tasks';
import { useTaskEvents } from '../lib/useTaskEvents';
import { captionFor, clipUrl, failedCalls, firstClip, nextClip, posterUrl, sceneFor, type Clip, type Presence, type SceneEvent, type SceneState } from '../lib/scene';
import { useSettings } from '../state/settings';
import type { ThreadTask } from './AgentThinking';

const PRESENCE_EVERY = 4000;

/** The assistant's workspace: asleep, waking or awake. Polled while the chat is open; the last answer stands through a failed request. */
function usePresence(task: ThreadTask | undefined): { presence: Presence; known: boolean } {
  const [presence, setPresence] = useState<Presence>('unknown'); const [known, setKnown] = useState(false);
  const state = task?.state;
  useEffect(() => {
    let stopped = false; let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      try { const r = await api<{ state: Presence }>('GET', '/v1/assistant/presence'); if (!stopped) setPresence(r.state); } catch { /* keep the last state */ }
      if (!stopped) setKnown(true);
      if (!stopped) timer = setTimeout(load, PRESENCE_EVERY);
    };
    void load();
    return () => { stopped = true; clearTimeout(timer); };
  }, [state]);                                                      // a task changing state is the moment the workspace most likely changed too
  return { presence, known };
}

/** One-off scenes the real task state calls for: a tool call failing while the task carries on, and the task ending. Never raised for history read on load. */
function useSceneEvent(task: ThreadTask | undefined, events: { kind: string; payload?: { category?: string; status?: string; ref?: string } }[], eventsTaskId: string | undefined) {
  const [event, setEvent] = useState<SceneEvent | null>(null);
  const failures = useRef<{ id?: string; n: number }>({ n: 0 });
  const last = useRef<{ id?: string; active: boolean }>({ active: false });
  const n = eventsTaskId === task?.id ? failedCalls(events) : 0;
  useEffect(() => {
    if (!task || eventsTaskId !== task.id) return;
    if (failures.current.id !== task.id) { failures.current = { id: task.id, n }; return; }          // first look at this task: just remember
    if (n > failures.current.n && isActive(task)) setEvent(n === 1 ? 'minor_obstacle' : 'moderate_obstacle');
    failures.current.n = n;
  }, [task?.id, eventsTaskId, n]);                                                             // eslint-disable-line react-hooks/exhaustive-deps
  const active = !!task && isActive(task);
  useEffect(() => {
    if (!task) return;
    if (last.current.id === task.id && last.current.active && !active) {
      if (task.state === 'completed') setEvent('completed');
      else if (task.state === 'failed') setEvent('failed');
    }
    last.current = { id: task.id, active };
  }, [task?.id, task?.state, active]);                                                         // eslint-disable-line react-hooks/exhaustive-deps
  return [event, useCallback(() => setEvent(null), [])] as const;
}

/**
 * The chat's background: the Lumina film, scene by scene. What plays is decided by the assistant's real state (workspace asleep or awake, the
 * latest task, its tool calls) and never by a timer. A scene finishes its current loop, plays its exit, then the next scene's entrance.
 * Two stacked videos hand over to each other so the next clip is already loaded when the current one ends.
 */
export default function SceneBackground({ task, ready, statusEl }: { task: ThreadTask | undefined; ready: boolean; statusEl?: HTMLElement | null }) {
  const { reducedMotion } = useSettings();
  const [paused, setPaused] = useState(() => { try { return localStorage.getItem('lumina.filmPaused') === '1'; } catch { return false; } });
  const togglePause = () => setPaused(p => { const next = !p; try { localStorage.setItem('lumina.filmPaused', next ? '1' : '0'); } catch { /* private mode: it just resets next visit */ } return next; });
  const active = !!task && isActive(task);
  const { presence, known } = usePresence(task);
  const { taskId, events } = useTaskEvents(task?.id, active);
  const taskEvents = taskId === task?.id ? events : [];
  const want = sceneFor(presence, task, taskEvents, active);
  const [event, clearEvent] = useSceneEvent(task, events, taskId);

  const wanted = useRef<SceneState>(want); wanted.current = want;
  const pending = useRef<SceneEvent | null>(null); pending.current = event;
  const [shown, setShown] = useState<SceneState>(want);              // the scene on screen: the poster behind the video, and the whole picture when motion is reduced
  const videos = [useRef<HTMLVideoElement>(null), useRef<HTMLVideoElement>(null)];
  const front = useRef(0); const [frontIdx, setFrontIdx] = useState(0);
  const head = useRef<Clip | null>(null);
  const [failed, setFailed] = useState(false);

  const setSource = (v: HTMLVideoElement, clip: Clip) => {
    const url = clipUrl(clip);
    if (v.dataset.clip !== url) { v.dataset.clip = url; v.src = url; v.load(); }
  };
  /** Keep the hidden video loaded with whatever would play next, whatever the latest state says. */
  const preload = useCallback(() => {
    const standby = videos[1 - front.current].current;
    if (standby && head.current) setSource(standby, nextClip(head.current, wanted.current, pending.current));
  }, []);                                                                                      // eslint-disable-line react-hooks/exhaustive-deps

  const advance = useCallback(() => {
    const current = head.current; const incoming = videos[1 - front.current].current; const outgoing = videos[front.current].current;
    if (!current || !incoming) return;
    const clip = nextClip(current, wanted.current, pending.current);
    if (clip.kind === 'event') clearEvent();
    setSource(incoming, clip);
    head.current = clip;
    incoming.currentTime = 0;
    incoming.play().then(() => {
      front.current = 1 - front.current; setFrontIdx(front.current);
      setShown(clip.scene);
      if (outgoing) { outgoing.pause(); }
      preload();
    }).catch(() => setFailed(true));
  }, [clearEvent, preload]);

  useEffect(() => {                                              // open on the right scene once the first state is known
    if (reducedMotion || paused || failed || head.current || !ready || !known) return;
    const v = videos[0].current; if (!v) return;
    front.current = 0; setFrontIdx(0);
    const clip = firstClip(wanted.current); head.current = clip; setShown(clip.scene);
    setSource(v, clip); v.play().then(preload).catch(() => setFailed(true));
  }, [reducedMotion, paused, failed, preload, ready, known]);                                                        // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (reducedMotion || paused) { head.current = null; setShown(want); } else preload(); }, [want, event, reducedMotion, paused]);   // eslint-disable-line react-hooks/exhaustive-deps

  const still = reducedMotion || paused || failed;
  return (
    <>
    <div className="scene" data-scene={shown} data-want={want}>
      <div className="scene-art" aria-hidden>
        <img className="scene-poster" src={posterUrl(still ? want : shown)} alt="" />
        {!still && videos.map((ref, i) => (
          <video key={i} ref={ref} className="scene-video" muted playsInline preload="auto" tabIndex={-1}
            style={{ opacity: i === frontIdx ? 1 : 0 }} onEnded={() => { if (i === front.current) advance(); }} onError={() => setFailed(true)} />))}
        <div className="scene-scrim" />
      </div>
    </div>
    {!reducedMotion && <button type="button" className="stage-pause" aria-pressed={paused} onClick={togglePause}>{paused ? 'Play animation' : 'Pause animation'}</button>}
    {/* With nothing running, say what Lumina is doing as a line in the conversation; running work is told by the orb's own label.
        The conversation is a polite live region, so falling asleep, waking or being stopped is announced there. */}
    {statusEl && !active && createPortal(<p className="thread-status-line" data-state={want}><span className="dot" aria-hidden />{captionFor(want, presence, task, taskEvents)}</p>, statusEl)}
  </>);

}
