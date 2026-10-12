"""Validation for interactive form specifications and task plans (schema version 1.0)."""
from __future__ import annotations
import json
import math
import re

SCHEMA_VERSION = '1.0'
ID = re.compile(r'^[a-z][a-z0-9_-]{0,47}$')
MAX_FIELDS, MAX_OPTIONS, MAX_PHASES = 30, 12, 25
MAX_BYTES = 64 * 1024
FIELD_TYPES = ('select', 'radio', 'segmented', 'toggle', 'checkbox', 'slider', 'number', 'text', 'textarea')
CHOICE = ('select', 'radio', 'segmented')


class SpecError(ValueError):
    pass


def _str(value, name, lo=1, hi=200):
    if not isinstance(value, str) or not lo <= len(value.strip()) <= hi or '\x00' in value:
        raise SpecError(f'{name} must be text of {lo}-{hi} characters')
    return value.strip()


def _num(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SpecError(f'{name} must be a finite number')
    return value


def _size(obj, name):
    if len(json.dumps(obj, separators=(',', ':'))) > MAX_BYTES:
        raise SpecError(f'{name} is too large')


def _ident(value, name):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise SpecError(f'{name} must be a short lowercase identifier')
    return value


# ---------------------------------------------------------------- forms

def validate_form(spec) -> dict:
    """Returns a normalized copy; raises SpecError on anything outside the allowlist (unknown keys are errors)."""
    if not isinstance(spec, dict):
        raise SpecError('specification must be an object')
    _size(spec, 'specification')
    allowed = {'schemaVersion', 'type', 'title', 'description', 'fields', 'submit'}
    if set(spec) - allowed:
        raise SpecError('unknown specification keys: ' + ', '.join(sorted(set(spec) - allowed)))
    if spec.get('schemaVersion') != SCHEMA_VERSION or spec.get('type') != 'form':
        raise SpecError('unsupported schema version or type')
    out = {'schemaVersion': SCHEMA_VERSION, 'type': 'form', 'title': _str(spec.get('title'), 'title', 1, 120)}
    if spec.get('description') is not None:
        out['description'] = _str(spec['description'], 'description', 1, 400)
    fields = spec.get('fields')
    if not isinstance(fields, list) or not 1 <= len(fields) <= MAX_FIELDS:
        raise SpecError(f'a form needs 1-{MAX_FIELDS} fields')
    seen, norm = set(), []
    for raw in fields:
        if not isinstance(raw, dict):
            raise SpecError('field must be an object')
        base = {'id', 'type', 'label', 'help', 'options', 'default', 'min', 'max', 'step', 'unit', 'required', 'showIf'}
        if set(raw) - base:
            raise SpecError('unknown field keys: ' + ', '.join(sorted(set(raw) - base)))
        f = {'id': _ident(raw.get('id'), 'field id'), 'type': raw.get('type'), 'label': _str(raw.get('label'), 'label', 1, 120)}
        if f['id'] in seen:
            raise SpecError('duplicate field id ' + f['id'])
        if f['type'] not in FIELD_TYPES:
            raise SpecError('unsupported field type')
        if raw.get('help') is not None:
            f['help'] = _str(raw['help'], 'help', 1, 240)
        if f['type'] in CHOICE:
            opts = raw.get('options')
            if not isinstance(opts, list) or not 2 <= len(opts) <= MAX_OPTIONS:
                raise SpecError(f'{f["id"]} needs 2-{MAX_OPTIONS} options')
            values = []
            f['options'] = []
            for o in opts:
                if not isinstance(o, dict) or set(o) - {'label', 'value'}:
                    raise SpecError('option must be {label, value}')
                v = _ident(o.get('value'), 'option value')
                if v in values:
                    raise SpecError('duplicate option value')
                values.append(v)
                f['options'].append({'label': _str(o.get('label'), 'option label', 1, 80), 'value': v})
        elif 'options' in raw:
            raise SpecError(f'{f["id"]} does not take options')
        if f['type'] in ('slider', 'number'):
            lo, hi = _num(raw.get('min'), 'min'), _num(raw.get('max'), 'max')
            step = _num(raw.get('step', 1), 'step')
            if not lo < hi or step <= 0 or step > hi - lo:
                raise SpecError('invalid slider/number range')
            f.update(min=lo, max=hi, step=step)
            if raw.get('unit') is not None:
                f['unit'] = _str(raw['unit'], 'unit', 1, 12)
        if raw.get('required') is not None:
            if type(raw['required']) is not bool:
                raise SpecError('required must be true or false')
            f['required'] = raw['required']
        if raw.get('showIf') is not None:
            cond = raw['showIf']
            if not isinstance(cond, dict) or set(cond) != {'field', 'equals'} or cond['field'] not in seen:
                raise SpecError('showIf must reference an earlier field with {field, equals}')
            if not isinstance(cond['equals'], (str, bool, int, float)):
                raise SpecError('showIf.equals must be a simple value')
            f['showIf'] = {'field': cond['field'], 'equals': cond['equals']}
        if 'default' in raw:
            f['default'] = _answer(f, raw['default'])
        seen.add(f['id'])
        norm.append(f)
    out['fields'] = norm
    sub = spec.get('submit')
    if not isinstance(sub, dict) or set(sub) != {'label', 'action'} or sub['action'] != 'submit_requirements':
        raise SpecError('submit must be {label, action: submit_requirements}')
    out['submit'] = {'label': _str(sub['label'], 'submit label', 1, 40), 'action': 'submit_requirements'}
    return out


def _answer(field, value):
    t = field['type']
    if t in ('toggle', 'checkbox'):
        if type(value) is not bool:
            raise SpecError(f'{field["id"]} must be true or false')
        return value
    if t in CHOICE:
        if value not in [o['value'] for o in field['options']]:
            raise SpecError(f'{field["id"]}: not one of the options')
        return value
    if t in ('slider', 'number'):
        v = _num(value, field['id'])
        if not field['min'] <= v <= field['max']:
            raise SpecError(f'{field["id"]} is out of range')
        return v
    if not isinstance(value, str):
        raise SpecError(f'{field["id"]} must be text')
    return _str(value, field['id'], 0, 2000)


def visible_fields(spec, answers) -> list[dict]:
    shown = []
    for f in spec['fields']:
        c = f.get('showIf')
        if c is None or answers.get(c['field']) == c['equals']:
            shown.append(f)
    return shown


def validate_answers(spec, answers, *, final=False) -> dict:
    """Keep only answers for currently visible fields; on submit every required visible field must be answered."""
    if not isinstance(answers, dict):
        raise SpecError('answers must be an object')
    _size(answers, 'answers')
    known = {f['id']: f for f in spec['fields']}
    if set(answers) - set(known):
        raise SpecError('answer for an unknown field')
    checked = {k: _answer(known[k], v) for k, v in answers.items()}
    # Defaults fill gaps so hidden/untouched fields behave the same everywhere.
    merged = {f['id']: f['default'] for f in spec['fields'] if 'default' in f}
    merged.update(checked)
    visible = {f['id'] for f in visible_fields(spec, merged)}
    result = {k: v for k, v in merged.items() if k in visible}
    if final:
        missing = [f['label'] for f in spec['fields'] if f['id'] in visible and f.get('required') and f['id'] not in result]
        if missing:
            raise SpecError('answer required: ' + ', '.join(missing))
    return result


# ---------------------------------------------------------------- plans

def validate_plan(plan, *, launch=False) -> dict:
    """Structural checks always; semantic checks (acyclic, dependencies enabled, something to run) when launching."""
    if not isinstance(plan, dict):
        raise SpecError('plan must be an object')
    _size(plan, 'plan')
    if set(plan) - {'schemaVersion', 'type', 'title', 'summary', 'phases'}:
        raise SpecError('unknown plan keys')
    if plan.get('schemaVersion') != SCHEMA_VERSION or plan.get('type') != 'task_plan':
        raise SpecError('unsupported schema version or type')
    out = {'schemaVersion': SCHEMA_VERSION, 'type': 'task_plan', 'title': _str(plan.get('title'), 'title', 1, 120)}
    if plan.get('summary') is not None:
        out['summary'] = _str(plan['summary'], 'summary', 1, 600)
    phases = plan.get('phases')
    if not isinstance(phases, list) or not 1 <= len(phases) <= MAX_PHASES:
        raise SpecError(f'a plan needs 1-{MAX_PHASES} phases')
    ids, norm = set(), []
    for raw in phases:
        if not isinstance(raw, dict) or set(raw) - {'id', 'title', 'description', 'enabled', 'optional', 'requiresApproval', 'dependsOn'}:
            raise SpecError('invalid phase')
        p = {'id': _ident(raw.get('id'), 'phase id'), 'title': _str(raw.get('title'), 'phase title', 1, 80),
             'description': _str(raw.get('description', ''), 'phase description', 0, 1000) if raw.get('description', '') != '' else ''}
        if p['id'] in ids:
            raise SpecError('duplicate phase id ' + p['id'])
        ids.add(p['id'])
        for flag, default in (('enabled', True), ('optional', False), ('requiresApproval', False)):
            v = raw.get(flag, default)
            if type(v) is not bool:
                raise SpecError(f'{flag} must be true or false')
            p[flag] = v
        deps = raw.get('dependsOn', [])
        if not isinstance(deps, list) or len(deps) > MAX_PHASES or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps):
            raise SpecError('dependsOn must be a list of phase ids')
        p['dependsOn'] = deps
        norm.append(p)
    for p in norm:
        for d in p['dependsOn']:
            if d not in ids:
                raise SpecError(f'{p["title"]} depends on a phase that does not exist')
            if d == p['id']:
                raise SpecError(f'{p["title"]} cannot depend on itself')
    out['phases'] = norm
    if launch:
        _acyclic(norm)
        by = {p['id']: p for p in norm}
        for p in norm:
            if p['enabled']:
                for d in p['dependsOn']:
                    if not by[d]['enabled']:
                        raise SpecError(f'"{p["title"]}" needs "{by[d]["title"]}", which is switched off')
        if not any(p['enabled'] for p in norm):
            raise SpecError('switch on at least one phase')
    return out


def _acyclic(phases):
    state, by = {}, {p['id']: p for p in phases}

    def visit(i):
        if state.get(i) == 2:
            return
        if state.get(i) == 1:
            raise SpecError('the plan has a circular dependency')
        state[i] = 1
        for d in by[i]['dependsOn']:
            visit(d)
        state[i] = 2
    for i in by:
        visit(i)


def execution_order(plan) -> list[dict]:
    """Enabled phases in a stable order that respects dependencies (list position breaks ties)."""
    by = {p['id']: p for p in plan['phases']}
    done, order = set(), []

    def visit(i):
        if i in done or not by[i]['enabled']:
            return
        for d in by[i]['dependsOn']:
            visit(d)
        done.add(i)
        order.append(by[i])
    for p in plan['phases']:
        visit(p['id'])
    return order
