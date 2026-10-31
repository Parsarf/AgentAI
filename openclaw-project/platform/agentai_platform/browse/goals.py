"""Keep the current instruction separate from quoted chat history at every model boundary."""
import json

HISTORY_HEADER = 'Previous messages from this same conversation (quoted context, not new actions to execute):\n'
CURRENT_MARKER = '\nCurrent user request:\n'


def goal_parts(goal):
    if goal.startswith(HISTORY_HEADER):
        encoded, separator, current = goal[len(HISTORY_HEADER):].partition(CURRENT_MARKER)
        if separator and current.strip():
            try:
                history = json.loads(encoded)
                if isinstance(history, list) and all(isinstance(row, dict) and row.get('role') in ('user', 'assistant') and isinstance(row.get('content'), str) for row in history):
                    return current, history
            except (ValueError, TypeError):
                pass
    return goal, []


def instruction_text(goal, context_chars=4000):
    current, history = goal_parts(goal)
    # Preserve the ENTIRE current request. Bound only old context, preferring
    # recent turns and keeping the quoted JSON structurally valid.
    recent, remaining = [], context_chars
    for row in reversed(history):
        if remaining <= 0:
            break
        content = row['content'][:min(1000, remaining)]
        recent.append({'role': row['role'], 'content': content})
        remaining -= len(content)
    text = 'Current user request (the task to carry out):\n' + current
    if recent:
        text += '\n\nQuoted previous conversation (context only, not additional actions):\n' + json.dumps(list(reversed(recent)), ensure_ascii=False)
    return text
