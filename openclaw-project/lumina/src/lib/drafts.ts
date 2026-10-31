export const draftKey = (account: string, conversation?: string | null) => `lumina:draft:${account}:${conversation || 'new'}`;
export function readDraft(key: string): string { try { return sessionStorage.getItem(key) ?? ''; } catch { return ''; } }
export function saveDraft(key: string, value: string) { try { value ? sessionStorage.setItem(key, value) : sessionStorage.removeItem(key); } catch { /* unavailable or full */ } }
export function clearDrafts() { try { for (const key of Object.keys(sessionStorage)) if (key.startsWith('lumina:draft:')) sessionStorage.removeItem(key); } catch { /* unavailable */ } }
