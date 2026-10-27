import AskBox from './AskBox';
import FieldsBox from './FieldsBox';
import type { Answer, Question } from '../lib/live';

/** The box for whatever the browser stopped to ask: a choice between the page's options, or the details a form needs. The same box is used in the chat and in the Live view. */
export default function QuestionPanel({ question, menuOpen, busy, onMenu, onAnswer, onCancel }: {
  question: Question; menuOpen: boolean; busy: boolean; onMenu: () => void; onAnswer: (body: Answer) => void; onCancel: () => void;
}) {
  if (question.kind === 'fields') return <FieldsBox key={question.id} question={question} menuOpen={menuOpen} busy={busy} onMenu={onMenu} onAnswer={onAnswer} onCancel={onCancel} />;
  return <AskBox key={question.id} question={question} menuOpen={menuOpen} busy={busy} onMenu={onMenu} onAnswer={onAnswer} />;
}
