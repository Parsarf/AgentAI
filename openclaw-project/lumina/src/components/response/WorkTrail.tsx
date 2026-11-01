import { useState } from 'react';
import type { Message } from '../../lib/conversations';
import AgentResponse from './AgentResponse';

/** The assistant's earlier messages for a finished request, folded under one button so the final answer is what you read. */
export default function WorkTrail({ messages }: { messages: Message[] }) {
  const [open, setOpen] = useState(false);
  const n = messages.length;
  return (
    <div className="work-trail">
      <button type="button" className="chip small work-trail-toggle" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        {open ? 'Hide the steps' : `Show the steps (${n})`}
      </button>
      {open && <div className="work-trail-body" role="group" aria-label="The assistant’s earlier messages for this answer">
        {messages.map(m => <div key={m.id} className="bubble agent"><AgentResponse content={m.content} /></div>)}
      </div>}
    </div>);
}
