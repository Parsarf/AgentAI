import { api } from '../lib/api';
// Fixed categories only: no labels, field values, document contents, exception text or URLs.
const recent = new Map<string, number>();
export function reportDiagnostic(artifact: string, version: number, kind: string, category: string): void {
  const key = `${artifact}:${kind}:${category}`;
  const now = Date.now();
  if (now - (recent.get(key) ?? 0) < 60_000) return;
  if (recent.size >= 200) recent.delete(recent.keys().next().value!);
  recent.set(key, now);
  void api('POST', `/v1/genui/artifacts/${artifact}/diagnostics`, { version, kind, category }, { timeoutMs: 5000 }).catch(() => {});
}
