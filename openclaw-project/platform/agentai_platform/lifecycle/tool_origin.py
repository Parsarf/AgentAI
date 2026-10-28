"""Resolve an MCP call from the pinned runtime's live turn and pending transcript.

MCP's static cell credential identifies an account, not a run. Never accept a
model-written request/session ID as authority. Unknown schemas, missing state,
completed calls, and ambiguous origins fail closed. No transcript leaves here.
"""
import io
import json
from contextlib import closing
import sqlite3
from pathlib import Path

TOOLS = {'lumina_browser', 'lumina_browser_step', 'lumina_task_update'}


def _db(root, relative):
    path = root / relative
    # The cell owns the contents; it cannot redirect a root reader elsewhere.
    for parent in (path, *path.parents):
        if parent.is_symlink():
            raise ValueError('symlink')
        if parent == root:
            break
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)


def _event(row):
    raw, compressed, size = row
    if size and size > 512_000:
        raise ValueError('oversize transcript')
    if raw is None and compressed is not None:
        from compression import zstd
        try:
            with zstd.ZstdFile(io.BytesIO(compressed)) as stream:
                raw = stream.read(512_001).decode()
        except zstd.ZstdError as error:
            raise ValueError('invalid compressed transcript') from error
    if not isinstance(raw, str) or len(raw) > 512_000:
        raise ValueError('invalid transcript')
    event = json.loads(raw)
    return event.get('message', event)


def active(root):
    """Bounded, read-only list of native turns; None means unverified, not idle."""
    try:
        with closing(_db(Path(root).absolute(), 'state/openclaw.sqlite')) as state:
            rows = state.execute('SELECT session_id,session_key,turn_claim_run_id FROM worker_session_placements WHERE turn_claim_id IS NOT NULL AND turn_claim_run_id IS NOT NULL LIMIT 33').fetchall()
        return rows if len(rows) <= 32 else None
    except (OSError, sqlite3.Error, ValueError):
        return None


def resolve(root, name, arguments):
    """Return the unique live {session_key, run_id, call_id}, or None."""
    if not isinstance(name, str) or name not in TOOLS or not isinstance(arguments, dict):
        return None
    root = Path(root).absolute()
    try:
        claims = active(root)
        if claims is None:
            return None
        matches = []
        with closing(_db(root, 'agents/main/agent/openclaw-agent.sqlite')) as agent:
            for session, key, run in claims:
                rows = agent.execute('''SELECT
                    CASE WHEN length(CAST(event_json AS BLOB)) <= 512000 THEN event_json END,
                    CASE WHEN length(event_zstd) <= 512000 THEN event_zstd END,
                    event_utf8_bytes FROM transcript_events WHERE session_id=? ORDER BY seq DESC LIMIT 8''', (session,)).fetchall()
                finished = set()
                for row in rows:
                    message = _event(row)
                    if message.get('role') == 'toolResult':
                        finished.add(message.get('toolCallId'))
                    if message.get('role') == 'user':
                        break
                    if message.get('role') != 'assistant':
                        continue
                    if (message.get('__openclaw') or {}).get('runId') != run:
                        break
                    for call in message.get('content') or []:
                        if not isinstance(call, dict) or call.get('type') not in ('toolCall', 'toolUse') or call.get('id') in finished:
                            continue
                        tool, args = call.get('name'), call.get('arguments')
                        if tool == 'tool_call' and isinstance(args, dict):
                            tool, args = args.get('id'), args.get('args')
                        if tool in (name, 'lumina__' + name, 'mcp:lumina:lumina__' + name) and args == arguments and call.get('id'):
                            matches.append({'session_key': key, 'run_id': run, 'call_id': call['id']})
                    # Only the newest assistant message may have pending calls.
                    break
        return matches[0] if len(matches) == 1 else None
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, AttributeError, ImportError):
        return None
