import type { SaveStatus } from './useAutosave';
const TEXT: Record<SaveStatus, string> = { saved: 'Saved', saving: 'Saving…', unsaved: 'Unsaved changes', conflict: 'Changed in another window — reload to continue', error: 'Could not save; retrying' };
export function Saved({ status }: { status: SaveStatus }) {
  return <span className={`faint save ${status}`} role="status" aria-live="polite">{TEXT[status]}</span>;
}
