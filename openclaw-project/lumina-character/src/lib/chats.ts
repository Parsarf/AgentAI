export interface ChatSummary { id: string; project_id: string; created_at: string; title: string | null; last_activity: string | null; active: number; preview?: string | null; archived_epoch?: number | null }

const stamp = (c: ChatSummary) => c.last_activity || c.created_at || '';
export const sortRecent = (list: ChatSummary[]) => [...list].sort((a, b) => stamp(b).localeCompare(stamp(a)));

/** Sidebar grouping by local calendar day of the last activity. */
export function groupLabel(c: ChatSummary, now = new Date()): 'Today' | 'Yesterday' | 'Earlier' {
  const d = new Date(stamp(c).replace(' ', 'T') + (/(?:[zZ]|[+-]\d\d:?\d\d)$/.test(stamp(c)) ? '' : 'Z'));
  if (isNaN(+d)) return 'Earlier';
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86400000);
  return diff <= 0 ? 'Today' : diff === 1 ? 'Yesterday' : 'Earlier';
}

export const chatTitle = (c: ChatSummary) => (c.title && c.title.trim()) || 'New chat';

/** Compact readable text for history previews; the full response keeps its Markdown. */
export const chatPreview = (value?: string | null) => (value || '')
  .replace(/```[\s\S]*?(?:```|$)/g, '')
  .replace(/!?\[([^\]]+)\]\([^)]*\)/g, '$1')
  .replace(/^\s{0,3}#{1,6}\s+/gm, '')
  .replace(/^\s*[-*+>]\s+/gm, '')
  .replace(/\*\*|__|~~|`/g, '')
  .replace(/\s+/g, ' ').trim();
