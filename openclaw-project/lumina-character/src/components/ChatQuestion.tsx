import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';
import { useBrowseQuestion } from '../lib/useBrowseQuestion';
import QuestionPanel from './QuestionPanel';

/** The browser's question, asked right under the message it belongs to. "Enter it myself" opens the Live view with the page ready to use. */
export default function ChatQuestion({ taskId, active, onChanged }: { taskId: string; active: boolean; onChanged?: () => void }) {
  const { question, busy, err, answer } = useBrowseQuestion(taskId, active); const nav = useNavigate();
  if (!question) return null;
  const cancel = async () => { try { await api('POST', `/v1/requests/${taskId}/cancel`, {}); } finally { onChanged?.(); } };
  return (
    <div className="chat-question">
      <QuestionPanel question={question} menuOpen={false} busy={busy} onMenu={() => nav(`/live/${taskId}?hands=1`)} onAnswer={b => { void answer(b); }} onCancel={cancel} />
      {err && <p className="err small" role="alert">{err}</p>}
    </div>);
}
