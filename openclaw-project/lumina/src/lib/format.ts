export function greeting(date: Date): string {
  const h = date.getHours();
  return h < 5 ? 'Good evening' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
}

/** No display name exists in the backend yet, so the first part of the email is used, tidied. */
export function displayName(email: string): string {
  const local = (email.split('@')[0] || '').split(/[._+-]/)[0] || 'there';
  return local.charAt(0).toUpperCase() + local.slice(1).toLowerCase();
}

export function ago(epochSeconds: number, nowMs: number = Date.now()): string {
  const s = Math.max(0, Math.floor(nowMs / 1000 - epochSeconds));
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function elapsed(epochSeconds: number, nowMs: number = Date.now()): string {
  const s = Math.max(0, Math.floor(nowMs / 1000 - epochSeconds));
  const m = Math.floor(s / 60);
  return m < 1 ? `${s}s` : `${m}m ${String(s % 60).padStart(2, '0')}s`;
}

export function title(message: string, max = 64): string {
  const one = message.replace(/\s+/g, ' ').trim();
  return one.length > max ? one.slice(0, max - 1).trimEnd() + '…' : one;
}
