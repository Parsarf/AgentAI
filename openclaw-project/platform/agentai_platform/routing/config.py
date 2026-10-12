"""Routing configuration (separate from browser-opt/config.json). Every number is a provisional default."""
from __future__ import annotations
import json
import math

ROUTES = ('deterministic', 'jev_executor', 'specialist_worker', 'claude', 'codex', 'abstain')
MODES = ('shadow', 'canary', 'live')

DEFAULTS = {
    'enabled': False,
    'mode': 'shadow',                       # shadow: record only. canary/live: may influence routing (not built yet)
    'canary_percent': 0,
    'primary_classifier': 'jev',
    'model': 'jev-1.13.0',
    'endpoint': 'https://api.typesafe.ai/v1/systemone',
    'deadline_s': 5,
    'routes': {'deterministic': False, 'jev_executor': False, 'specialist_worker': False, 'claude': True, 'codex': False},
    'confidence': {'automatic': 0.85, 'review': 0.65},
    'escalation': {'enabled': True, 'max_escalations': 2, 'max_retries_per_step': 2},
    'verification': {'required': True},
    'limits': {'max_task_duration_seconds': 1800, 'max_task_cost_usd': 1.00},
    'telemetry': {'enabled': True, 'redact_sensitive_data': True},
    # Price used only to ESTIMATE classifier cost; version is recorded with every estimate. Not a provider charge.
    'pricing': {'version': 'typesafe-jev-1.13.0-2026-09-27', 'input_usd_per_mtok': 0.042, 'output_usd_per_mtok': 0.0},
}


class ConfigError(ValueError):
    pass


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if k not in base:
            raise ConfigError('unknown routing setting: ' + str(k))
        if isinstance(base[k], dict):
            if not isinstance(v, dict):
                raise ConfigError(k + ' must be an object')
            out[k] = _merge(base[k], v)
        else:
            out[k] = v
    return out


def _num(value, lo, hi, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ConfigError(f'{name} must be a number between {lo} and {hi}')


def validate(cfg: dict) -> dict:
    if cfg['mode'] not in MODES:
        raise ConfigError('mode must be one of ' + ', '.join(MODES))
    if type(cfg['enabled']) is not bool:
        raise ConfigError('enabled must be true or false')
    if type(cfg['canary_percent']) is not int or not 0 <= cfg['canary_percent'] <= 100:
        raise ConfigError('canary_percent must be 0-100')
    _num(cfg['confidence']['automatic'], 0, 1, 'confidence.automatic')
    _num(cfg['confidence']['review'], 0, 1, 'confidence.review')
    if cfg['confidence']['review'] > cfg['confidence']['automatic']:
        raise ConfigError('review threshold cannot exceed the automatic threshold')
    if set(cfg['routes']) - set(ROUTES) or any(type(v) is not bool for v in cfg['routes'].values()):
        raise ConfigError('routes must map known route names to true/false')
    _num(cfg['escalation']['max_escalations'], 0, 10, 'escalation.max_escalations')
    _num(cfg['escalation']['max_retries_per_step'], 0, 10, 'escalation.max_retries_per_step')
    _num(cfg['limits']['max_task_duration_seconds'], 1, 86400, 'limits.max_task_duration_seconds')
    _num(cfg['limits']['max_task_cost_usd'], 0.01, 5.0, 'limits.max_task_cost_usd')   # never above the plan's $5 task cap
    _num(cfg['deadline_s'], 1, 30, 'deadline_s')
    if not str(cfg['endpoint']).startswith('https://'):
        raise ConfigError('endpoint must be https')
    return cfg


def load(path) -> dict:
    """Missing or unreadable file = defaults (disabled). A malformed file is an error, never silently partial."""
    try:
        with open(path) as handle:
            override = json.load(handle)
    except FileNotFoundError:
        return validate(_merge(DEFAULTS, {}))
    if not isinstance(override, dict):
        raise ConfigError('routing config must be an object')
    return validate(_merge(DEFAULTS, override))
