"""Cards the assistant can attach to an answer: table, chart, comparison, places, products, steps, answer, choice, callout, timeline, sources.

The assistant writes up to three fenced blocks, ```lumina {json}```, after its short text answer, and only when a card helps. Server code validates it against a strict
allowlist (no HTML, only http(s) links, bounded sizes) and stores it as a block; anything that fails is dropped and the plain text stays.
"""
from __future__ import annotations
import json
import math
import re

from ..browse.untrusted import MARK, neutralize
from .schema import SpecError

FENCE = re.compile(r'```lumina[ \t]*\n(.*?)```', re.S)
KINDS = ('table', 'chart', 'comparison', 'places', 'products', 'steps', 'answer', 'choice', 'callout', 'timeline', 'sources')
WITH_PICTURES = ('comparison', 'places', 'products')       # kinds whose items may get a picture from their own `link` (images.py)
CONFIDENCE = ('confirmed', 'likely', 'uncertain')
TONES = ('info', 'tip', 'warning', 'success')
COLUMN_TYPES = ('text', 'number', 'currency', 'percent', 'rating', 'link')
CHART_TYPES = ('bar', 'line', 'pie', 'donut')
MAX_ROWS, MAX_COLS, MAX_POINTS, MAX_SERIES, MAX_ITEMS, MAX_BYTES = 200, 12, 40, 4, 6, 48 * 1024
MAX_ACTIONS, ACTION_MIN, ACTION_MAX = 4, 4, 90
COL_ID = re.compile(r'^[a-z][a-z0-9_]{0,31}$')


def _t(v, name, hi, lo=1):
    if not isinstance(v, str) or not lo <= len(v.strip()) <= hi or '\x00' in v or '<' in v and '>' in v:
        raise SpecError(f'{name} must be plain text of {lo}-{hi} characters')
    return v.strip()


def _actions(v, name='actions'):
    """Follow-ups the assistant offers on a card: up to 4 short sentences. The sentence is BOTH the button's label and the message that is sent when it is pressed, so what a person
    reads is exactly what is sent (nothing hidden behind a label). It reaches the chat as the person's own message, so a sentence aimed at the AI (text a web page planted) is dropped."""
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > MAX_ACTIONS:
        raise SpecError(f'at most {MAX_ACTIONS} {name}')
    out, seen = [], set()
    for x in v:
        text = _t(x, name[:-1], ACTION_MAX, ACTION_MIN)
        if MARK in neutralize(text) or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
    return out


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
    out = {'table': _table, 'chart': _chart, 'comparison': _comparison, 'places': _places, 'products': _products, 'steps': _steps, 'answer': _answer,
           'choice': _choice, 'callout': _callout, 'timeline': _timeline, 'sources': _sources}[kind](spec)
    actions = _actions(spec.get('actions'))
    if actions:
        out['actions'] = actions                                  # absent when there are none, so a card without follow-ups is stored exactly as before
    return out


def _table(spec):
    _only(spec, {'schemaVersion', 'type', 'title', 'caption', 'columns', 'rows', 'highlightRow', 'actions'}, 'table')
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
    _only(spec, {'schemaVersion', 'type', 'title', 'caption', 'chart', 'labels', 'series', 'unit', 'actions'}, 'chart')
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
    _only(spec, {'schemaVersion', 'type', 'title', 'caption', 'items', 'bestIndex', 'actions'}, 'comparison')
    items = spec.get('items')
    if not isinstance(items, list) or not 2 <= len(items) <= MAX_ITEMS:
        raise SpecError(f'compare 2-{MAX_ITEMS} items')
    out_items = []
    for it in items:
        _only(it, {'name', 'subtitle', 'badge', 'price', 'link', 'facts', 'pros', 'cons', 'actions'}, 'item')
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
        item_actions = _actions(it.get('actions'))
        if item_actions:
            o['actions'] = item_actions
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



# ---- the richer cards -----------------------------------------------------------------------------------------------------------------------------
def _opt(src, out, key, hi):
    if src.get(key) is not None:
        out[key] = _t(src[key], key, hi)


def _range(v, name, lo, hi, integer=False):
    v = _n(v, name)
    if integer and int(v) != v or not lo <= v <= hi:
        raise SpecError(f'{name} must be between {lo} and {hi}')
    return int(v) if integer else v


def _items(spec, lo, hi, name='items'):
    items = spec.get(name)
    if not isinstance(items, list) or not lo <= len(items) <= hi:
        raise SpecError(f'{lo}-{hi} {name}')
    return items


def _head(spec, kind, title=True):
    out = {'schemaVersion': '1.0', 'type': kind}
    if title:
        out['title'] = _t(spec.get('title'), 'title', 120)
    _opt(spec, out, 'caption', 240)
    return out


def _places(spec):
    _only(spec, {'schemaVersion', 'type', 'title', 'caption', 'items', 'actions'}, 'places')
    out = _head(spec, 'places')
    out['items'] = []
    for it in _items(spec, 1, 10):
        _only(it, {'name', 'link', 'address', 'area', 'rating', 'reviews', 'price', 'distance', 'distance_km', 'open', 'hours', 'tags', 'note', 'actions'}, 'place')
        o = {'name': _t(it.get('name'), 'name', 80)}
        if it.get('link') is not None:
            o['link'] = _url(it['link'], 'link')
        for key, hi in (('address', 140), ('area', 60), ('price', 12), ('distance', 24), ('hours', 60), ('note', 200)):
            _opt(it, o, key, hi)
        if it.get('rating') is not None:
            o['rating'] = _range(it['rating'], 'rating', 0, 5)
        if it.get('reviews') is not None:
            o['reviews'] = _range(it['reviews'], 'reviews', 0, 10**8, integer=True)
        if it.get('distance_km') is not None:
            o['distance_km'] = _range(it['distance_km'], 'distance_km', 0, 20000)
        if it.get('open') is not None:
            if not isinstance(it['open'], bool):
                raise SpecError('open must be true or false')
            o['open'] = it['open']
        tags = it.get('tags', [])
        if not isinstance(tags, list) or len(tags) > 4:
            raise SpecError('at most 4 tags')
        o['tags'] = [_t(x, 'tag', 24) for x in tags]
        acts = _actions(it.get('actions'))
        if acts:
            o['actions'] = acts
        out['items'].append(o)
    return out


def _products(spec):
    _only(spec, {'schemaVersion', 'type', 'title', 'caption', 'items', 'actions'}, 'products')
    out = _head(spec, 'products')
    out['items'] = []
    for it in _items(spec, 1, 12):
        _only(it, {'name', 'link', 'price', 'price_value', 'store', 'rating', 'reviews', 'badge', 'specs', 'note', 'actions'}, 'product')
        o = {'name': _t(it.get('name'), 'name', 100)}
        if it.get('link') is not None:
            o['link'] = _url(it['link'], 'link')
        for key, hi in (('price', 24), ('store', 40), ('badge', 24), ('note', 200)):
            _opt(it, o, key, hi)
        if it.get('price_value') is not None:
            o['price_value'] = _range(it['price_value'], 'price_value', 0, 10**9)
        if it.get('rating') is not None:
            o['rating'] = _range(it['rating'], 'rating', 0, 5)
        if it.get('reviews') is not None:
            o['reviews'] = _range(it['reviews'], 'reviews', 0, 10**8, integer=True)
        specs = it.get('specs', [])
        if not isinstance(specs, list) or len(specs) > 6:
            raise SpecError('at most 6 specs')
        o['specs'] = []
        for f in specs:
            _only(f, {'label', 'value'}, 'spec')
            o['specs'].append({'label': _t(f.get('label'), 'spec label', 40), 'value': _t(f.get('value'), 'spec value', 80)})
        acts = _actions(it.get('actions'))
        if acts:
            o['actions'] = acts
        out['items'].append(o)
    return out


def _steps(spec):
    _only(spec, {'schemaVersion', 'type', 'title', 'caption', 'items', 'actions'}, 'steps')
    out = _head(spec, 'steps')
    out['items'] = []
    for it in _items(spec, 1, 20):
        _only(it, {'title', 'detail'}, 'step')
        o = {'title': _t(it.get('title'), 'step title', 140)}
        _opt(it, o, 'detail', 400)
        out['items'].append(o)
    return out


def _sources_list(raw, lo, hi):
    if raw is None and lo == 0:
        return []
    if not isinstance(raw, list) or not lo <= len(raw) <= hi:
        raise SpecError(f'{lo}-{hi} sources')
    out = []
    for src in raw:
        _only(src, {'title', 'link', 'site', 'note'}, 'source')
        o = {'title': _t(src.get('title'), 'source title', 120), 'link': _url(src.get('link'), 'source link')}
        _opt(src, o, 'site', 60)
        _opt(src, o, 'note', 200)
        out.append(o)
    return out


def _answer(spec):
    _only(spec, {'schemaVersion', 'type', 'title', 'headline', 'value', 'detail', 'confidence', 'sources', 'actions'}, 'answer')
    out = {'schemaVersion': '1.0', 'type': 'answer', 'headline': _t(spec.get('headline'), 'headline', 200)}
    for key, hi in (('title', 60), ('value', 40), ('detail', 600)):
        _opt(spec, out, key, hi)
    if spec.get('confidence') is not None:
        if spec['confidence'] not in CONFIDENCE:
            raise SpecError('confidence must be confirmed, likely or uncertain')
        out['confidence'] = spec['confidence']
    out['sources'] = _sources_list(spec.get('sources'), 0, 6)
    return out


def _choice(spec):
    """A question with buttons. Pressing one (or sending the ticked ones) sends exactly the visible words, like a follow-up; an option aimed at the AI is dropped."""
    _only(spec, {'schemaVersion', 'type', 'question', 'options', 'multiple'}, 'choice')
    options = _actions_like(spec.get('options'), 'options', 2, 8, 1, 60)
    if len(options) < 2:
        raise SpecError('a choice needs at least 2 different options')
    out = {'schemaVersion': '1.0', 'type': 'choice', 'question': _t(spec.get('question'), 'question', 200), 'options': options}
    if spec.get('multiple') is not None:
        if not isinstance(spec['multiple'], bool):
            raise SpecError('multiple must be true or false')
        out['multiple'] = spec['multiple']
    return out


def _actions_like(v, name, lo, hi, min_len, max_len):
    if not isinstance(v, list) or not lo <= len(v) <= hi:
        raise SpecError(f'{lo}-{hi} {name}')
    out, seen = [], set()
    for x in v:
        text = _t(x, name, max_len, min_len)
        if MARK in neutralize(text) or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text)
    return out


def _callout(spec):
    _only(spec, {'schemaVersion', 'type', 'tone', 'title', 'text'}, 'callout')
    tone = spec.get('tone', 'info')
    if tone not in TONES:
        raise SpecError('tone must be info, tip, warning or success')
    out = {'schemaVersion': '1.0', 'type': 'callout', 'tone': tone, 'text': _t(spec.get('text'), 'text', 400)}
    _opt(spec, out, 'title', 80)
    return out


def _timeline(spec):
    _only(spec, {'schemaVersion', 'type', 'title', 'caption', 'items', 'actions'}, 'timeline')
    out = _head(spec, 'timeline')
    out['items'] = []
    for it in _items(spec, 1, 20):
        _only(it, {'when', 'title', 'detail'}, 'moment')
        o = {'when': _t(it.get('when'), 'when', 40), 'title': _t(it.get('title'), 'title', 140)}
        _opt(it, o, 'detail', 300)
        out['items'].append(o)
    return out


def _sources(spec):
    _only(spec, {'schemaVersion', 'type', 'title', 'items'}, 'sources')
    out = {'schemaVersion': '1.0', 'type': 'sources', 'title': _t(spec.get('title', 'Sources'), 'title', 60), 'items': _sources_list(spec.get('items'), 1, 10)}
    return out


LIST_LINE = re.compile(r'^\s{0,3}(?:[-*+]|\d{1,2}[.)])\s+')


def _base_name(name: str) -> str:
    """The part of an item's name a sentence would use: 'Haidilao Hot Pot - Unfiltered red chili broth' -> 'haidilao hot pot'."""
    return re.split(r'\s[-\u2013\u2014|(]\s?', name, maxsplit=1)[0].strip().lower()


def trim_repeats(text: str, specs: list) -> str:
    """A reply that put places, products or options in a card sometimes lists the same things again as bullets above it, so the person sees everything twice,
    once without pictures. Remove the list lines that name the card's items (with whatever follows them up to the next list line or blank line), only when at
    least two such lines are found; every other line stays, so the intro and the closing sentences are kept and a passing mention is never touched."""
    names = {_base_name(it['name']) for spec in specs if spec.get('type') in WITH_PICTURES for it in spec.get('items', [])}
    names = {n for n in names if len(n) >= 4}
    if not names or not text:
        return text
    lines, drop, i = text.split('\n'), set(), 0
    while i < len(lines):
        if LIST_LINE.match(lines[i]) and any(n in lines[i].lower() for n in names):
            j = i + 1                                        # the item's continuation lines (indented, not a new item, not blank) go with it
            while j < len(lines) and lines[j].strip() and not LIST_LINE.match(lines[j]) and lines[j][:1].isspace():
                j += 1
            drop.update(range(i, j))
            i = j
            continue
        i += 1
    if len({k for k in drop if LIST_LINE.match(lines[k])}) < 2:
        return text
    kept = '\n'.join(l for k, l in enumerate(lines) if k not in drop)
    return re.sub(r'\n{3,}', '\n\n', kept).strip()


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
