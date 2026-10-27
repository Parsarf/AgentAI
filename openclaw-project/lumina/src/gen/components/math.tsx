import { useEffect, useRef, useState } from 'react';
import katex from 'katex';
/** Strict, bounded TeX -> native accessible MathML. No trusted macros, URLs, HTML or script output. */
export default function MathView({ source }: { source: string }) {
  const root = useRef<HTMLDivElement>(null); const [error, setError] = useState('');
  useEffect(() => { try { katex.render(source, root.current!, { output: 'mathml', displayMode: true, throwOnError: true, trust: false, strict: 'error', maxExpand: 200, maxSize: 10 }); setError(''); } catch { root.current?.replaceChildren(); setError('This formula could not be typeset. Correct its TeX syntax.'); } }, [source]);
  return <figure><div className="gen-scroll" tabIndex={0} ref={root} aria-label="Mathematical formula" />{error && <p role="alert">{error}</p>}<details><summary>Formula source</summary><code>{source}</code></details></figure>;
}
