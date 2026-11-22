import { useEffect, useState } from 'react';

/** The size of one element, kept current as it changes: a page uses it to fit its own controls to the room it has, which is not the window's when a side column is
 *  dragged, hidden, or the assistant is docked. -> [ref to put on the element, its size]. The size is 0 by 0 until it is known (and where it cannot be measured);
 *  callers treat that as "roomy". */
export function useSize<T extends HTMLElement>(): [(node: T | null) => void, { width: number; height: number }] {
  const [node, setNode] = useState<T | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    if (!node || typeof ResizeObserver === 'undefined') return;
    const read = () => { const r = node.getBoundingClientRect(); const width = Math.round(r.width), height = Math.round(r.height);
      setSize(s => (s.width === width && s.height === height ? s : { width, height })); };
    read();
    const watch = new ResizeObserver(read); watch.observe(node);
    return () => watch.disconnect();
  }, [node]);
  return [setNode, size];
}
