"""Read-only data cards (table, chart, comparison) the assistant can attach to an answer.

The assistant writes one fenced block, ```lumina {json}```, after its short text answer. Server code validates it against a strict
allowlist (no HTML, only http(s) links, bounded sizes) and stores it as a block; anything that fails is dropped and the plain text stays.
"""
from __future__ import annotations
import json
import math
import re

from .schema import SpecError

FENCE = re.compile(r'```lumina[ \t]*\n(.*?)```', re.S)
KINDS = ('table', 'chart', 'comparison')
COLUMN_TYPES = ('text', 'number', 'currency', 'percent', 'rating', 'link')
CHART_TYPES = ('bar', 'line', 'pie', 'donut')
MAX_ROWS, MAX_COLS, MAX_POINTS, MAX_SERIES, MAX_ITEMS, MAX_BYTES = 200, 12, 40, 4, 6, 48 * 1024
COL_ID = re.compile(r'^[a-z][a-z0-9_]{0,31}$')


def _t(v, name, hi, lo=1):
    if not isinstance(v, str) or not lo <= len(v.strip()) <= hi or '\x00' in v or '<' in v and '>' in v:
        raise SpecError(f'{name} must be plain text of {lo}-{hi} characters')
    return v.strip()


def _n(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or abs(v) > 1e15:
        raise SpecError(f'{name} must be a finite number')
    return v


def _url(v, name):
    v = _t(v, name, 500)
    if not re.match(r'^https?://[^\s]+$', v, re.I):
        raise SpecError(f'{name} must be an http(s) link')
    return v


def _only(obj, allowed, name):
    if not isinstance(obj, dict) or set(obj) - set(allowed):
        raise SpecError(f'invalid {name}')


def validate_data(spec) -> dict:
    if not isinstance(spec, dict) or len(json.dumps(spec, separators=(',', ':'))) > MAX_BYTES:
        raise SpecError('card must be an object under 48 KB')
    kind = spec.get('type')
    if spec.get('schemaVersion', '1.0') != '1.0' or kind not in KINDS:
        raise SpecError('unsupported card type')
    return {'table': _table, 'chart': _chart, 'comparison': _comparison}[kind](spec)


def _table(spec):
    _only(spec, {'schemaVersion', 'type', 'title', 'caption', 'columns', 'rows', 'highlightRow'}, 'table')
    cols, rows = spec.get('columns'), spec.get('rows')
    if not isinstance(cols, list) or not 1 <= len(cols) <= MAX_COLS or not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise SpecError(f'a table needs 1-{MAX_COLS} columns and 1-{MAX_ROWS} rows')
    out_cols, ids = [], set()
    for c in cols:
        _only(c, {'id', 'label', 'type', 'unit'}, 'column')
        cid = c.get('id')
        if not isinstance(cid, str) or not COL_ID.fullmatch(cid) or cid in ids:
            raise SpecError('column ids must be short, lowercase and unique')
        ids.add(cid)
        ctype = c.get('type', 'text')
        if ctype not in COLUMN_TYPES:
            raise SpecError('unsupported column type')
        col = {'id': cid, 'label': _t(c.get('label'), 'column label', 60), 'type': ctype}
        if c.get('unit') is not None:
            col['unit'] = _t(c['unit'], 'unit', 12)
        out_cols.append(col)
    out_rows = []
    for r in rows:
        if not isinstance(r, dict) or set(r) - ids:
            raise SpecError('row has a value for an unknown column')
        row = {}
        for col in out_cols:
            if col['id'] not in r or r[col['id']] is None:
                continue
            v = r[col['id']]
            row[col['id']] = _n(v, col['label']) if col['type'] in ('number', 'currency', 'percent', 'rating') else (_url(v, col['label']) if col['type'] == 'link' else _t(v, col['label'], 300, 0))
        out_rows.append(row)
    out = {'schemaVersion': '1.0', 'type': 'table', 'title': _t(spec.get('title'), 'title', 120), 'columns': out_cols, 'rows': out_rows}
    if spec.get('caption') is not None:
        out['caption'] = _t(spec['caption'], 'caption', 240)
    if spec.get('highlightRow') is not None:
        h = spec['highlightRow']
        if type(h) is not int or not 0 <= h < len(out_rows):
            raise SpecError('highlightRow is out of range')
        out['highlightRow'] = h
    return out


def _chart(spec):
    _only(spec, {'schemaVersion', 'type', 'title', 'caption', 'chart', 'labels', 'series', 'unit'}, 'chart')
    ctype, labels, series = spec.get('chart'), spec.get('labels'), spec.get('series')
    if ctype not in CHART_TYPES or not isinstance(labels, list) or not 1 <= len(labels) <= MAX_POINTS or not isinstance(series, list) or not 1 <= len(series) <= MAX_SERIES:
        raise SpecError('a chart needs a type, 1-40 labels and 1-4 series')
    if ctype in ('pie', 'donut') and len(series) != 1:
        raise SpecError('pie and donut charts take one series')
    out_series = []
    for s in series:
        _only(s, {'name', 'values'}, 'series')
        vals = s.get('values')
        if not isinstance(vals, list) or len(vals) != len(labels):
            raise SpecError('every series needs one value per label')
        vals = [_n(v, 'value') for v in vals]
        if ctype in ('pie', 'donut') and any(v < 0 for v in vals):
            raise SpecError('pie values cannot be negative')
        out_series.append({'name': _t(s.get('name'), 'series name', 60), 'values': vals})
    out = {'schemaVersion': '1.0', 'type': 'chart', 'chart': ctype, 'title': _t(spec.get('title'), 'title', 120),
           'labels': [_t(str(l) if isinstance(l, (int, float)) and not isinstance(l, bool) else l, 'label', 60) for l in labels], 'series': out_series}
    for k, hi in (('caption', 240), ('unit', 12)):
        if spec.get(k) is not None:
            out[k] = _t(spec[k], k, hi)
    return out


def _comparison(spec):
    _only(spec, {'schemaVersion', 'type', 'title', 'caption', 'items', 'bestIndex'}, 'comparison')
    items = spec.get('items')
    if not isinstance(items, list) or not 2 <= len(items) <= MAX_ITEMS:
        raise SpecError(f'compare 2-{MAX_ITEMS} items')
    out_items = []
    for it in items:
        _only(it, {'name', 'subtitle', 'badge', 'price', 'link', 'facts', 'pros', 'cons'}, 'item')
        o = {'name': _t(it.get('name'), 'name', 80)}
        for k, hi in (('subtitle', 120), ('badge', 24), ('price', 24)):
            if it.get(k) is not None:
                o[k] = _t(it[k], k, hi)
        if it.get('link') is not None:
            o['link'] = _url(it['link'], 'link')
        facts = it.get('facts', [])
        if not isinstance(facts, list) or len(facts) > 10:
            raise SpecError('at most 10 facts per item')
        o['facts'] = []
        for f in facts:
            _only(f, {'label', 'value'}, 'fact')
            o['facts'].append({'label': _t(f.get('label'), 'fact label', 40), 'value': _t(f.get('value'), 'fact value', 120)})
        for k in ('pros', 'cons'):
            lst = it.get(k, [])
            if not isinstance(lst, list) or len(lst) > 5:
                raise SpecError(f'at most 5 {k}')
            o[k] = [_t(x, k, 120) for x in lst]
        out_items.append(o)
    out = {'schemaVersion': '1.0', 'type': 'comparison', 'title': _t(spec.get('title'), 'title', 120), 'items': out_items}
    if spec.get('caption') is not None:
        out['caption'] = _t(spec['caption'], 'caption', 240)
    if spec.get('bestIndex') is not None:
        b = spec['bestIndex']
        if type(b) is not int or not 0 <= b < len(out_items):
            raise SpecError('bestIndex is out of range')
        out['bestIndex'] = b
    return out


def extract(text: str):
    """(clean_text, [valid specs]). Fences that are malformed or fail validation are removed from the text and dropped."""
    specs = []

    def take(match):
        try:
            specs.append(validate_data(json.loads(match.group(1))))
        except (ValueError, SpecError):
            pass
        return ''
    clean = FENCE.sub(take, text or '')
    clean = re.sub(r'```lumina[ \t]*\n.*\Z', '', clean, flags=re.S)        # an unfinished fence at the end is never shown
    return re.sub(r'\n{3,}', '\n\n', clean).strip(), specs[:3]
