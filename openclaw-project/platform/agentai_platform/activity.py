"""Customer-visible activity from the assistant's own tool use (searching, reading, commands, file changes).

The runtime history lists each tool call the assistant makes. This module turns those raw rows into a few short, bounded,
redacted items for the Activity window. Nothing raw leaves here: only a fixed set of categories, a label, a short detail
(query, address, command, path) and, for commands only, a trimmed redacted output. File contents are never shown.
"""
from __future__ import annotations
import re
from urllib.parse import urlsplit

from .events import redact

MAX_DETAIL = 300
MAX_OUTPUT = 1200
EXTRA_SECRETS = [
    re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}'),
    re.compile(r'(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD)[A-Z0-9_]*)\s*=\s*\S+'),
    re.compile(r'(?i)(authorization|x-api-key)\s*:\s*\S+'),
    re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)', re.S),
]

CATEGORY = {
    'spawn_agent': 'subagent', 'sessions_spawn': 'subagent', 'subagents': 'subagent',
    'web_search': 'search', 'search': 'search', 'brave_search': 'search',
    'web_fetch': 'read', 'fetch': 'read', 'browser': 'browse', 'lumina_browser': 'browse', 'lumina__lumina_browser': 'browse',
    'exec': 'command', 'bash': 'command', 'shell': 'command', 'process': 'command',
    'write': 'file', 'edit': 'file', 'apply_patch': 'file', 'read': 'file',
}
LABELS = {
    'search': 'Searched the web', 'read': 'Opened a page', 'command': 'Ran a command', 'browse': 'Used the browser',
    'file': 'Worked with a file', 'other': 'Used a tool',
}
WORKSPACE = '/home/node/.openclaw/workspace/'
HIDDEN = {'tool_search', 'tool_describe'}                  # runtime housekeeping, not customer-relevant work
FILE_VERBS = {'write': 'Wrote', 'edit': 'Edited', 'apply_patch': 'Edited', 'read': 'Read'}


def clean(text, limit):
    text = redact(str(text or ''))
    for pattern in EXTRA_SECRETS:
        text = pattern.sub('[redacted]', text)
    text = text.replace('\x00', '').strip()
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _args(block):
    for key in ('arguments', 'input', 'args', 'params'):
        value = block.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _first(args, *names):
    for name in names:
        value = args.get(name)
        if isinstance(value, str) and value.strip():
            return value
    return ''


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b.get('text', '') for b in content if isinstance(b, dict) and isinstance(b.get('text'), str))
    return ''


def _page(url):
    try:
        parts = urlsplit(url)
    except ValueError:
        return ''
    if parts.scheme not in ('http', 'https') or not parts.hostname:
        return ''
    return parts.hostname + (parts.path if parts.path not in ('', '/') else '')


def describe(name, args):
    """-> (category, label, detail)"""
    tool = str(name or '').lower()
    category = CATEGORY.get(tool, 'other')
    if category == 'search':
        return category, 'Searched the web', clean(_first(args, 'query', 'q'), MAX_DETAIL)
    if category == 'read':
        return category, 'Opened a page', clean(_page(_first(args, 'url', 'uri')) or _first(args, 'url'), MAX_DETAIL)
    if category == 'command':
        return category, 'Ran a command', clean(re.sub(r'^cd /home/node/\.openclaw/workspace\s*&&\s*', '', _first(args, 'command', 'cmd', 'script')).replace(WORKSPACE, ''), MAX_DETAIL)
    if category == 'file':
        path = _first(args, 'path', 'file', 'file_path', 'filename').replace(WORKSPACE, '')
        return category, f'{FILE_VERBS.get(tool, "Worked with")} a file', clean(path, MAX_DETAIL)
    if category == 'browse':
        return category, 'Used the browser', clean(_first(args, 'site', 'action', 'url', 'task'), MAX_DETAIL)
    if category == 'subagent':
        return category, 'Delegated to an agent', clean(_first(args, 'label', 'task', 'message'), MAX_DETAIL)
    label = clean(re.sub(r'[_-]+', ' ', tool), 40) or 'tool'
    return 'other', f'Used {label}', ''


def extract(raw_messages):
    """Raw runtime history rows -> [{ref, tool, category, label, detail, output, status}] in call order.

    status is 'running' until the matching result row is present, then 'done' or 'failed'. `run_id` and `after` (the input it followed) say whose call it was (not part of what is shown):
    the driver keeps only the calls of the runs and inputs it owns.
    """
    calls, order = {}, []
    for message in raw_messages or []:
        if not isinstance(message, dict):
            continue
        role, content = message.get('role'), message.get('content')
        if role == 'assistant' and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict) or block.get('type') not in ('toolCall', 'tool_use', 'toolUse'):
                    continue
                ref = block.get('id')
                if not isinstance(ref, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', ref) or ref in calls:
                    continue
                name, args = block.get('name'), _args(block)
                if name in HIDDEN:
                    continue
                if name == 'tool_call':                        # the runtime's wrapper for tools it discovered by search: show the real tool
                    inner = args.get('id')
                    name = inner.rsplit(':', 1)[-1] if isinstance(inner, str) else 'tool'
                    args = args.get('args') if isinstance(args.get('args'), dict) else {}
                category, label, detail = describe(name, args)
                calls[ref] = {'ref': ref, 'tool': clean(name, 40), 'category': category, 'label': label,
                              'detail': detail, 'output': '', 'status': 'running', 'run_id': (message.get('__openclaw') or {}).get('runId'), 'after': message.get('__after')}
                order.append(ref)
        elif role in ('toolResult', 'tool'):
            ref = message.get('toolCallId') or message.get('tool_call_id')
            item = calls.get(ref)
            if item is None:
                continue
            item['status'] = 'failed' if message.get('isError') or message.get('is_error') else 'done'
            if item['category'] == 'command' or item['status'] == 'failed':
                item['output'] = clean(_text(content), MAX_OUTPUT)
    return [calls[ref] for ref in order]
