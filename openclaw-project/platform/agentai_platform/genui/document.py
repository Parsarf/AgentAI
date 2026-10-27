"""Composed answers: ordered blocks (text, tables, charts, cards, forms, agent widgets) that the assistant writes in a ```lumina-doc fence after its prose.

The server is the authority. A document is validated here, against the SAME schemas the browser uses: `gen_registry.json` is generated from
lumina/src/gen/schemas.ts (a test fails when it drifts). Anything that fails validation is replaced by its plain-text fallback, never stored as-is, so a
reload shows exactly what the first view showed. The assistant writes data and props only: no HTML, no CSS, no code, no links except http(s),
no images from addresses (an image is a file in the customer's own files), and agent actions only from the registered list.

Wire format: either one JSON document {"version","responseId","blocks":[...],"datasets":{...}} or JSON Lines (an optional {"responseId"} line, {"dataset":id,...}
lines, then one block per line); the second form lets a streaming client mount each block as soon as its line is complete.
"""
from __future__ import annotations
import json
import re
from functools import lru_cache
from pathlib import Path

from .schema import SpecError

FENCE = re.compile(r'```lumina-doc[ \t]*\n(.*?)```', re.S)
UNFINISHED = re.compile(r'```lumina-doc[ \t]*\n.*\Z', re.S)
_CONTROL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_HTMLISH = re.compile(r'<\s*/?\s*[a-zA-Z!][^>]*>')
_BIDI = re.compile('[‪-‮⁦-⁩]')
RAW_FIELDS = {('code_block', 'code'), ('terminal_output', 'lines'), ('json_viewer', 'json'), ('diff_viewer', 'diff')}   # code and output may contain < and >
URL_KEYS = {'url', 'externalUrl'}
INTERNAL_ROUTES = ('/chat', '/tasks', '/files', '/live', '/history', '/calendar', '/settings')
CONTAINER_KEYS = {'tabs': ('tabs', 'blocks'), 'accordion': ('items', 'blocks'), 'section': (None, 'blocks')}


@lru_cache(maxsize=1)
def registry() -> dict:
    with open(Path(__file__).with_name('gen_registry.json'), encoding='utf-8') as handle:
        return json.load(handle)


# ---- a small JSON Schema interpreter (only the keywords gen_registry.json uses; a test enforces that list) -------------------------------------
def _type_ok(kind: str, value) -> bool:
    if kind == 'object':
        return isinstance(value, dict)
    if kind == 'array':
        return isinstance(value, list)
    if kind == 'string':
        return isinstance(value, str)
    if kind == 'boolean':
        return isinstance(value, bool)
    if kind == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == 'null':
        return value is None
    return False


def _fail(path: str, message: str):
    raise SpecError(f'{path or "block"}: {message}')


def _check(schema: dict, value, root: dict, path: str = '') -> None:
    if '$ref' in schema:
        if schema['$ref'] != '#':
            _fail(path, 'unsupported reference')
        return _check(root, value, root, path)
    if 'not' in schema:
        _fail(path, 'not allowed')                       # only used as `not: {}` (a property that must be absent)
    if 'anyOf' in schema or 'oneOf' in schema:
        options = schema.get('oneOf') or schema.get('anyOf')
        errors = []
        for option in options:
            try:
                _check(option, value, root, path)
                return
            except SpecError as error:
                errors.append(str(error))
        # a discriminated union: report the error of the option whose `type` matched, not the last one tried
        pick = next((e for o, e in zip(options, errors) if isinstance(value, dict) and o.get('properties', {}).get('type', {}).get('const') == value.get('type')), None)
        _fail(path, (pick or 'no allowed shape matches').split(': ', 1)[-1] if pick else 'no allowed shape matches')
    if 'const' in schema and value != schema['const']:
        _fail(path, 'unexpected value')
    if 'enum' in schema and value not in schema['enum']:
        _fail(path, 'not an allowed value')
    kind = schema.get('type')
    if kind is not None and not any(_type_ok(k, value) for k in (kind if isinstance(kind, list) else [kind])):
        _fail(path, f'expected {kind}')
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', 10 ** 9):
            _fail(path, 'wrong length')
        if 'pattern' in schema and not re.search(schema['pattern'], value):
            _fail(path, 'wrong format')
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value != value or value in (float('inf'), float('-inf')):
            _fail(path, 'must be finite')
        for key, test in (('minimum', lambda a, b: a >= b), ('maximum', lambda a, b: a <= b), ('exclusiveMinimum', lambda a, b: a > b), ('exclusiveMaximum', lambda a, b: a < b)):
            if key in schema and not test(value, schema[key]):
                _fail(path, 'out of range')
    if isinstance(value, list):
        if len(value) < schema.get('minItems', 0) or len(value) > schema.get('maxItems', 10 ** 9):
            _fail(path, 'wrong number of items')
        if 'items' in schema:
            for n, item in enumerate(value):
                _check(schema['items'], item, root, f'{path}[{n}]')
    if isinstance(value, dict):
        props = schema.get('properties', {})
        for key in schema.get('required', []):
            if key not in value:
                _fail(f'{path}.{key}'.lstrip('.'), 'is required')
        if 'propertyNames' in schema:
            for key in value:
                _check(schema['propertyNames'], key, root, path)
        extra = schema.get('additionalProperties', True)
        for key, item in value.items():
            where = f'{path}.{key}'.lstrip('.')
            if key in props:
                _check(props[key], item, root, where)
            elif extra is False:
                _fail(where, 'is not allowed')
            elif isinstance(extra, dict):
                _check(extra, item, root, where)


# ---- checks JSON Schema cannot express (the browser applies the same rules in safety.ts / schemas.ts) ----------------------------------------
def _safe_url(v) -> bool:
    if not isinstance(v, str) or len(v) > 500 or _CONTROL.search(v):
        return False
    m = re.match(r'^(https?)://([^/?#]*)', v, re.I)
    return bool(m) and '@' not in m.group(2) and bool(m.group(2))


def _safe_internal(v) -> bool:
    if not isinstance(v, str) or len(v) > 200 or _CONTROL.search(v) or '\\' in v or v.startswith('//'):
        return False
    path = re.split(r'[?#]', v)[0]
    return '..' not in path.split('/') and any(path == r or path.startswith(r + '/') for r in INTERNAL_ROUTES)


def _safe_file(v) -> bool:
    return isinstance(v, str) and 0 < len(v) <= 300 and not _CONTROL.search(v) and '\\' not in v and not v.startswith('/') and not re.match(r'^[a-z][a-z0-9+.-]*:', v, re.I) \
        and not any(s in ('', '.', '..') for s in v.split('/'))


def _scan(value, block_type: str, key: str = '', path: str = '') -> None:
    if isinstance(value, str):
        if (block_type, key) in RAW_FIELDS:
            return
        if _CONTROL.search(value) or _HTMLISH.search(value) or _BIDI.search(value):
            _fail(path, 'contains markup, control or direction-override characters')
        if key in URL_KEYS and not _safe_url(value):
            _fail(path, 'must be an http(s) link')
        if key == 'assetRef' and not (value.startswith('file:') and _safe_file(value[5:])):
            _fail(path, 'must be a file in your files')
    elif isinstance(value, list):
        for n, item in enumerate(value):
            _scan(item, block_type, key, f'{path}[{n}]')
    elif isinstance(value, dict):
        if value.get('kind') == 'navigate.internal' and not _safe_internal(value.get('path')):
            _fail(path, 'that page is not allowed')
        if value.get('kind') == 'file.download':
            _fail(path, 'downloads are not offered yet')
        for k, item in value.items():
            _scan(item, block_type, k, f'{path}.{k}'.lstrip('.'))


def _children(block: dict) -> list:
    spec = CONTAINER_KEYS.get(block.get('type'))
    props = block.get('props') or {}
    if not spec:
        return []
    group, inner = spec
    if group is None:
        return list(props.get(inner) or [])
    return [child for entry in props.get(group) or [] for child in (entry.get('blocks') or [])]


def _shape(blocks: list, depth: int = 1) -> tuple[int, int]:
    count, deepest = 0, depth if blocks else 0
    for b in blocks:
        count += 1
        c, d = _shape(_children(b) if isinstance(b, dict) else [], depth + 1)
        count, deepest = count + c, max(deepest, d if c else depth)
    return count, deepest


def validate_block(block, datasets: dict | None = None) -> dict:
    reg = registry()
    if not isinstance(block, dict) or block.get('type') not in reg['offered']:
        raise SpecError('this component is not available')
    _check(reg['blockSchema'], block, reg['blockSchema'])
    _scan(block, block['type'])
    props = block.get('props') or {}
    if block.get('variant') in ('stacked', 'comparative') and len(props.get('series') or []) < 2:
        raise SpecError('that chart variant needs at least two series')
    if block.get('visible') is False:
        pass
    count, depth = _shape(_children(block))
    if depth > reg['limits']['depth'] - 1 or count > reg['limits']['nested']:
        raise SpecError('nested blocks are too deep or too many')
    if block.get('dataRef') is not None and block['dataRef'] not in (datasets or {}):
        raise SpecError(f'dataRef "{block["dataRef"]}" does not exist in this response')
    for child in _children(block):                       # nested blocks must be offered and safe too (the schema already checked their shape)
        validate_block(child, datasets)
    return block


def _fallback_text(block) -> str:
    if not isinstance(block, dict):
        return ''
    if isinstance(block.get('fallback'), str) and block['fallback'].strip():
        return block['fallback'].strip()[:600]
    props = block.get('props') if isinstance(block.get('props'), dict) else {}
    bits = [props[k] for k in ('title', 'label', 'text', 'content', 'description') if isinstance(props.get(k), str) and props[k].strip()]
    return ' — '.join(bits)[:600]


def _clean_text(text: str) -> str | None:
    text = text.strip()
    if not text or _CONTROL.search(text) or _HTMLISH.search(text) or _BIDI.search(text):
        return None
    return text


def validate_document(raw) -> dict:
    """-> the normalised document to store. Raises SpecError only when nothing usable is left."""
    reg = registry()
    if not isinstance(raw, dict):
        raise SpecError('a document is an object')
    version = raw.get('version', reg['schemaVersion'] if isinstance(raw.get('blocks'), list) else None)
    if not isinstance(version, str) or version.split('.')[0] != reg['schemaVersion'].split('.')[0]:
        raise SpecError('unsupported document version')
    rid = raw.get('responseId', 'migrated')
    if not isinstance(rid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', rid):
        raise SpecError('invalid responseId')
    blocks = raw.get('blocks')
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= reg['limits']['blocks']:
        raise SpecError(f'a document has 1-{reg["limits"]["blocks"]} blocks')
    datasets = {}
    for key, ds in (raw.get('datasets') or {}).items():
        try:
            _check(reg['datasetSchema'], ds, reg['datasetSchema'])
            _scan(ds, 'dataset')
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]{0,63}', key):
                raise SpecError('bad dataset id')
            datasets[key] = ds
        except SpecError:
            continue                                       # a bad dataset only fails the blocks that reference it
    out, seen = [], set()
    for block in blocks:
        bid = block.get('id') if isinstance(block, dict) else None
        if bid in seen:
            continue
        try:
            out.append(validate_block(block, datasets))
            seen.add(bid)
        except SpecError:
            text = _clean_text(_fallback_text(block))
            if text and isinstance(bid, str) and re.fullmatch(r'[a-z][a-z0-9_-]{0,47}', bid):      # the useful part of a failed block survives as plain text
                out.append({'id': bid, 'type': 'text', 'props': {'content': text, 'format': 'plain'}})
                seen.add(bid)
    if not out:
        raise SpecError('no usable block')
    doc = {'version': reg['schemaVersion'], 'responseId': rid, 'blocks': out}
    used = {b.get('dataRef') for b in out if isinstance(b, dict)} | {r for b in out for r in _nested_refs(b)}
    if datasets:
        doc['datasets'] = {k: v for k, v in datasets.items() if k in used}
    plan = raw.get('presentationPlan')
    if plan is not None:
        try:
            doc['presentationPlan'] = validate_presentation_plan(plan)
        except SpecError:
            pass                                            # advisory only; never blocks the answer
    if len(json.dumps(doc, separators=(',', ':'))) > reg['limits']['bytes']:
        raise SpecError('document too large')
    return doc


def _nested_refs(block) -> set:
    refs = set()
    for child in _children(block) if isinstance(block, dict) else []:
        refs.add(child.get('dataRef'))
        refs |= _nested_refs(child)
    return refs


def validate_presentation_plan(plan) -> dict:
    """JEV's advisory presentation plan. It names components and purposes; it never carries data, props or code."""
    reg = registry()
    _check(reg['presentationPlanSchema'], plan, reg['presentationPlanSchema'])
    _scan(plan, 'plan')
    for entry in plan['blocks']:
        if entry['componentId'] not in reg['offered']:
            raise SpecError('plan names a component that is not available')
        allowed = reg['variants'].get(entry['componentId'], [])
        if entry.get('variant') and entry['variant'] not in allowed:
            raise SpecError('plan names a variant the component does not have')
    return plan


# ---- extraction from an assistant reply --------------------------------------------------------------------------------------------------------
def _from_lines(body: str) -> dict:
    out = {'version': registry()['schemaVersion'], 'responseId': 'lines', 'blocks': [], 'datasets': {}}
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        if isinstance(item.get('dataset'), str):
            out['datasets'][item['dataset']] = {k: v for k, v in item.items() if k != 'dataset'}
        elif isinstance(item.get('presentationPlan'), dict):
            out['presentationPlan'] = item['presentationPlan']
        elif 'type' not in item and isinstance(item.get('responseId'), str):
            out['responseId'] = item['responseId'][:64]
        elif isinstance(item.get('type'), str):
            out['blocks'] = [b for b in out['blocks'] if b.get('id') != item.get('id')] + [item]
    return out


def extract_documents(text: str):
    """(clean_text, [documents]). The fence is always removed from the text; an invalid or oversized one is dropped; at most one document is kept."""
    docs = []

    def take(match):
        body = match.group(1).strip()
        if len(body) > registry()['limits']['bytes'] * 2:
            return ''
        try:
            try:
                raw = json.loads(body)
                if not (isinstance(raw, dict) and 'blocks' in raw):
                    raw = _from_lines(body)
            except ValueError:
                raw = _from_lines(body)
            docs.append(validate_document(raw))
        except (SpecError, ValueError, KeyError, TypeError):
            pass
        return ''
    clean = FENCE.sub(take, text or '')
    clean = UNFINISHED.sub('', clean)                       # an unfinished fence is never shown
    return re.sub(r'\n{3,}', '\n\n', clean).strip(), [dict(d, type='document') for d in docs[:1]]


def rules_section() -> str:
    """The text added to the assistant's rules file: the compact catalog (offered components only) and the envelope. Built from the registry, so it cannot promise more than exists."""
    reg = registry()
    return (
        '## Composed answers (lumina-doc)\n'
        'Most answers are plain text. When one answer is clearest as prose plus a table, a chart, cards or a form, write the prose first (it is shown at once), then ONE fenced block whose '
        'language is `lumina-doc`. Inside it write JSON Lines: an optional first line {"responseId":"r1"}, then {"dataset":"id","columns":[{"id":"month","label":"Month"},...],"rows":[...]} '
        'lines for data shared by several blocks, then one block per line: {"id":"trend","type":"line_chart","dataRef":"id","props":{...}}. A block is {id, type, variant?, dataRef?, props:{...}}; '
        'ids are lowercase letters, digits, - or _. Plain text only in props (no HTML, no markdown except in `text`, `list`, `callout`, `quote`, `info_card.body`). '
        'Use real values from your work or from pages you read; never invent numbers, prices, places or sources, and leave a block out when you do not have its data. '
        'A fallback sentence (`fallback`) lets a block degrade to text. For tables or charts with more than 60 rows put the rows in a dataset (up to 500) and refer to it with dataRef. '
        'Agent widgets (execution_timeline, agent_status, plan_viewer, approval_request, error_retry, completion_summary) take only ids of tasks or plans that exist in this chat; '
        'their contents come from Lumina, never from you. Actions are limited to: ' + ', '.join(reg['actions']) + '. Buttons and form submissions send exactly their words as the person\'s next message. '
        'Pick by what the answer is: prose for explanations; info_card for one entity; table for several attributes; line_chart/area_chart for trends over time; bar_chart for categories; scatter_chart for a relationship; '
        'timeline for steps in order; form only when the reader should change inputs; agent widgets only for tasks that exist. Never chart fewer than 4 points. Components (nothing else exists):\n' + reg['catalogCompact'] + '\n'
    )
