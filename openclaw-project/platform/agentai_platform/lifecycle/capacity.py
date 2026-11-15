"""How many customer cells this host may carry. One owner setting, read fresh each time (default 2: the private-beta limit)."""
from __future__ import annotations
import json
import os

DEFAULT = 2
HARD_MAX = 200
PATH = os.environ.get('AGENTAI_SIGNUP_SETTINGS_FILE', '/var/lib/agentai-platform/signup-settings.json')


def max_cells(path=None):
    try:
        value = json.load(open(path or PATH)).get('max_accounts')
    except (OSError, ValueError, AttributeError):
        return DEFAULT
    return value if type(value) is int and 1 <= value <= HARD_MAX else DEFAULT


def setting(key, default, path=None):
    """One owner setting from the signup settings file, read fresh each time."""
    try:
        return json.load(open(path or PATH)).get(key, default)
    except (OSError, ValueError, AttributeError):
        return default


def max_running_cells(path=None):
    """The most customer cells that may run at the same moment. None (the default) means "as many as the host's live capacity admits": memory, CPU, disk and
    process counts decide, and requests beyond it wait in line. An owner may set a lower ceiling (1 to 200), e.g. 1 to go back to one customer at a time."""
    value = setting('max_running_cells', None, path)
    return value if type(value) is int and 1 <= value <= HARD_MAX else None


def set_max_running_cells(value, path=None):
    if value is not None and (type(value) is not int or not 1 <= value <= HARD_MAX):
        raise ValueError('running cells must be a whole number from 1 to %d, or empty for "by host capacity"' % HARD_MAX)
    target = path or PATH
    tmp = target + '.new'
    try:
        current = json.load(open(target))
    except (OSError, ValueError):
        current = {}
    if value is None:
        current.pop('max_running_cells', None)
    else:
        current['max_running_cells'] = value
    with open(tmp, 'w') as handle:
        json.dump(current, handle)
    os.replace(tmp, target)
    return value


def set_max_cells(value, path=None):
    if type(value) is not int or not 1 <= value <= HARD_MAX:
        raise ValueError('customer limit must be a whole number from 1 to %d' % HARD_MAX)
    target = path or PATH
    tmp = target + '.new'
    try:
        current = json.load(open(target))
    except (OSError, ValueError):
        current = {}
    current['max_accounts'] = value
    with open(tmp, 'w') as handle:
        json.dump(current, handle)
    os.replace(tmp, target)
    return value
