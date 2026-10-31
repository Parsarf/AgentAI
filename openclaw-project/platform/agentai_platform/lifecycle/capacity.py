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
