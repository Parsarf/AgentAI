"""Host-owned Lumina model catalog. Never accepts endpoint/key configuration from customers."""
import json
import os
import re
from pathlib import Path

DEFAULT = {'id': 'lumina-default', 'name': 'Lumina', 'model': 'claude-sonnet-5-5'}


def models():
    path = os.environ.get('AGENTAI_MODEL_CATALOG_FILE', '')
    if not path:
        return [dict(DEFAULT)]
    try:
        rows = json.loads(Path(path).read_text())['models']
        if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
            raise ValueError()
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {'id', 'name', 'model'}:
                raise ValueError()
            if not all(isinstance(row[k], str) for k in row):
                raise ValueError()
            if not re.fullmatch(r'lumina-[a-z0-9-]{1,50}', row['id']) or row['id'] in seen or not 1 <= len(row['name']) <= 80 or not re.fullmatch(r'[A-Za-z0-9_./:-]{1,120}', row['model']):
                raise ValueError()
            seen.add(row['id'])
        if DEFAULT['id'] not in seen:
            raise ValueError()
        return rows
    except (OSError, ValueError, KeyError, TypeError):
        # Broken configuration must never advertise unverified extra routes.
        return [dict(DEFAULT)]


def find(model_id):
    return next((m for m in models() if m['id'] == model_id), None)
