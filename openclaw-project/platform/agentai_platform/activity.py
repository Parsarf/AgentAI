"""Customer-visible activity from the assistant's own tool use (searching, reading, commands, file changes).

The runtime history lists each tool call the assistant makes. This module turns those raw rows into a few short, bounded,
redacted items for the Activity window. Nothing raw leaves here: only a fixed set of categories, a label, a short detail
(query, address, command, path) and, for commands only, a trimmed redacted output. File contents are never shown.
"""
from __future__ import annotations
import json
import re
from urllib.parse import urlsplit

from . import faults
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
    'lumina_browser_step': 'browse', 'lumina__lumina_browser_step': 'browse',
    'exec': 'command', 'bash': 'command', 'shell': 'command', 'process': 'command',
    'write': 'file', 'edit': 'file', 'apply_patch': 'file', 'read': 'file',
}
LABELS = {
    'search': 'Searched the web', 'read': 'Opened a page', 'command': 'Ran a command', 'browse': 'Used the browser',
    'file': 'Worked with a file', 'other': 'Used a tool',
}
WORKSPACE = '/home/node/.openclaw/workspace/'
HIDDEN = {'tool_search', 'tool_describe', 'lumina_task_update', 'lumina__lumina_task_update', 'lumina_mcp_discover', 'lumina__lumina_mcp_discover'}                  # runtime housekeeping, not customer-relevant work
# Lumina's own tools that have no category: what the customer reads instead of the raw tool name ("Used lumina lumina mcp call").
OWN_LABELS = {'lumina_mcp_call': 'Used a connected service', 'lumina_mcp_search': 'Looked for a service to connect', 'lumina_mcp_setup': 'Set up a connection',
              'lumina_mcp_connections': 'Checked your connections', 'lumina_memory_recall': 'Recalled a memory', 'lumina_memory_remember': 'Saved a memory',
              'lumina_request_location': 'Asked for your location', 'lumina_file_deliver': 'Prepared a file for you', 'lumina_show': 'Prepared a visual answer'}
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
    own = tool.removeprefix('lumina__')
    if own in OWN_LABELS:
        return 'other', OWN_LABELS[own], ''
    if re.fullmatch(r'lumina_mcp_[a-f0-9]{32}_[a-f0-9]{12}', own):
        return 'other', OWN_LABELS['lumina_mcp_call'], ''
    label = clean(re.sub(r'[_-]+', ' ', tool), 40) or 'tool'
    return 'other', f'Used {label}', ''


# The runtime wraps what a tool outside it answered (Lumina's tools, a fetched page) in a notice for the model and a marked block. That notice is the runtime talking to the
# model: stored as the step's output it filled the whole 1,200 characters, so every failed step of a Lumina tool showed the customer "SECURITY NOTICE: The following
# content is from an EXTERNAL, UNTRUSTED source" and nothing of why it failed (production, 30 days to 2026-11-24: 134 of 194 failed steps).
_BLOCK = re.compile(r'<<<EXTERNAL_UNTRUSTED_CONTENT[^>]*>>>\s*(.*?)\s*(?:<<<END_EXTERNAL_UNTRUSTED_CONTENT[^>]*>>>|\Z)', re.S)
_NOTICE = 'SECURITY NOTICE:'


def _json(text):
    try:
        value = json.loads(text)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def own_words(text) -> str:
    """What the tool itself said, out of the runtime's wrapping. Three layers are taken off, each only when it is there: the `tool_call` wrapper's {"error": ...}, the marked
    block with its "Source: ..." head, and the {"tool", "result": {"content": [...]}} record of a tool the runtime reached over MCP. Text that is not wrapped comes back as
    it is. What a page said after "Web fetch failed (403):" is itself wrapped in a second notice and is dropped with it: only the tool's own words are kept."""
    text = str(text or '')
    outer = _json(text)
    if outer is not None and isinstance(outer.get('error'), str):
        text = outer['error']
    found = _BLOCK.search(text)
    if found:
        text = found.group(1)
        head, rule, rest = text.partition('\n---\n')
        if rule and head.startswith('Source:') and '\n' not in head:
            text = rest
        inner = _json(text)
        if inner is None and text.lstrip().startswith('{'):           # the record was cut short by the runtime's own limit: the first text of the result is still readable
            cut = re.search(r'"text":\s*("(?:[^"\\]|\\.)*")', text)
            if cut:
                try:
                    text = json.loads(cut.group(1))
                except ValueError:
                    pass
        elif inner is not None:
            result = inner.get('result') if isinstance(inner.get('result'), dict) else inner
            said = _text(result.get('content'))
            if said:
                text = said
    at = text.find(_NOTICE)
    if at >= 0:
        text = text[:at].rstrip(' :\n')
    return text.strip()


def extract(raw_messages):
    """Raw runtime history rows -> [{ref, tool, category, label, detail, output, status}] in call order.

    status is 'running' until the matching result row is present, then 'done' or 'failed'. `run_id` and `after` (the input it followed) say whose call it was (not part of what is shown):
    the driver keeps only the calls of the runs and inputs it owns. A failed call also carries `reason`: the registered reason read from what the runtime said about it
    (faults.of_runtime_tool). For one of Lumina's own tools (`own`) the driver replaces it with the reason the tool relay recorded when the call was made, which is a fact.
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
                if name in HIDDEN:
                    continue
                category, label, detail = describe(name, args)
                calls[ref] = {'ref': ref, 'tool': clean(name, 40), 'category': category, 'label': label, 'own': str(name or '').startswith('lumina_'),
                              'detail': detail, 'output': '', 'status': 'running', 'run_id': (message.get('__openclaw') or {}).get('runId'), 'after': message.get('__after')}
                order.append(ref)
        elif role in ('toolResult', 'tool'):
            ref = message.get('toolCallId') or message.get('tool_call_id')
            item = calls.get(ref)
            if item is None:
                continue
            item['status'] = 'failed' if message.get('isError') or message.get('is_error') else 'done'
            if item['category'] == 'command' or item['status'] == 'failed':
                said = own_words(_text(content))
                item['output'] = clean(said, MAX_OUTPUT)
                if item['status'] == 'failed':
                    item['reason'] = faults.of_runtime_tool(item['tool'], said).reason
    return [calls[ref] for ref in order]
