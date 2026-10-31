"""Reads, from the code itself, every fact the privacy policy depends on.

The policy (deploy/vercel/public/privacy.html) makes statements about what Lumina collects, who receives it and how long it is kept. Each of those statements
rests on something in the code: a retention constant, an extension permission, a host the server talks to, a column that holds personal data. This module
reads those things back out of the source so tests/test_privacy_policy.py can compare them with the reviewed record in privacy/facts.json. When they differ,
the test fails and says which fact moved: that is the moment to ask "does the policy still tell the truth?" (see README.md).

    python3 privacy/derive.py          # prints what the code says right now, as JSON
"""
from __future__ import annotations
import ast
import hashlib
import inspect
import json
import re
import sys
import tempfile
from pathlib import Path

PLATFORM = Path(__file__).resolve().parents[1]
PROJECT = PLATFORM.parent
EXTENSION = PROJECT / 'browse' / 'extension'
sys.path.insert(0, str(PLATFORM))


def _read(path):
    return Path(path).read_text()


def _days(source):
    """Every `timedelta(days=N)` in a source text, in order."""
    return [int(n) for n in re.findall(r'timedelta\(days=(\d+)\)', source)]


def _storage_keys(text):
    """The names of the things the extension keeps in chrome.storage.local (on the customer's computer), read from its get / set / remove calls."""
    keys = set()
    for m in re.finditer(r"storage\.local\.(?:get|remove)\(\s*(\[[^\]]*\]|'[^']*')\s*\)", text):
        keys |= set(re.findall(r"'([^']+)'", m.group(1)))
    for m in re.finditer(r"storage\.local\.set\(\s*\{([^}]*)\}", text):
        keys |= set(re.findall(r"(?:^|,)\s*([A-Za-z_]\w*)\s*:", m.group(1)))
    return keys


def retention():
    from agentai_platform import events
    from agentai_platform.browse import service
    from agentai_platform.ops import backup, housekeeping
    sig = inspect.signature(housekeeping.prune_snapshots).parameters
    real_name = 'backup-20261012T174815Z-premigrate-20261012T1830Z-ops.sqlite3'        # what deploy/release.py really produces
    return {
        'browse_pictures_and_trace_hours': service.SCREENSHOT_RETENTION_SECONDS / 3600,
        'browse_purge_every_minutes': service.PURGE_EVERY_SECONDS / 60,
        'encrypted_backups_max_days': backup.MAX_AGE_DAYS,
        'encrypted_backups_daily_kept': backup.KEEP_DAILY, 'encrypted_backups_weekly_kept': backup.KEEP_WEEKLY,
        'plaintext_snapshots_keep_newest': sig['keep'].default, 'plaintext_snapshots_max_days': sig['max_age_days'].default,
        'plaintext_snapshot_cleanup_matches_real_names': bool(housekeeping.PATTERN.fullmatch(real_name)),
        # defined in code, enforced by nothing that is scheduled (see scheduled_retention_jobs): the policy must not promise them
        'defined_but_unscheduled': {
            'event_timeline_days': events.RETENTION_DAYS,
            'retention_command_days': _days(_read(PLATFORM / 'accounts' / 'management' / 'commands' / 'retention_accounts.py')),
        },
        # anything in deploy/ that schedules a deletion of customer data: a new one means the policy can say more (or must say something different)
        'scheduled_retention_jobs': sorted(str(p.relative_to(PLATFORM)) for p in (PLATFORM / 'deploy').rglob('*')
                                           if p.is_file() and p.suffix in ('.service', '.timer', '.cron', '.sh', '.py') and re.search(r'retention_accounts|prune_expired', p.read_text(errors='ignore'))),
    }


def extension():
    manifest = json.loads(_read(EXTENSION / 'manifest.json'))
    code = {p.name: _read(p) for p in (EXTENSION / 'src').glob('*.js')}
    keys = sorted(set().union(*(_storage_keys(text) for text in code.values())))
    page = code['page.js']
    return {
        'permissions': sorted(manifest.get('permissions', [])),
        'host_permissions': manifest.get('host_permissions', []) + manifest.get('optional_host_permissions', []),
        'page_may_message_it': manifest.get('externally_connectable', {}).get('matches', []),
        'server': re.search(r"PROD_BRIDGE = '([^']+)'", code['config.js']).group(1),
        'stored_on_the_computer': keys,
        'page_text_limit_chars': int(re.search(r'\.slice\(0,\s*(\d+)\)\s*,\s*scroll', page.replace('\n', ' ')).group(1)) if re.search(r'\.slice\(0,\s*(\d+)\)\s*,\s*scroll', page.replace('\n', ' ')) else None,
        'max_controls_listed': int(re.search(r'MAX_ELEMENTS = (\d+)', code['rules.js']).group(1)),
        'secret_field_values_withheld': "secret = type === 'password'" in page and 'if (!secret)' in page,
        'loads_remote_code': any(re.search(r'\beval\(|new Function\(|importScripts\(|<script[^>]+src="https?:', text) for text in list(code.values()) + [_read(EXTENSION / 'popup.html')]),
        'network_calls_other_than_the_server': [name for name, text in code.items() if re.search(r'\bfetch\(|XMLHttpRequest|navigator\.sendBeacon', text)],
    }


# every host the product's own code names, minus ones that are only examples or documentation links
IGNORED_HOSTS = {'example.com', 'localhost', 'www.w3.org', 'creativecommons.org', 'openmoji.org', 'github.com', 'docs.openclaw.ai'}


def hosts():
    found = set()
    roots = [PLATFORM / 'agentai_platform', PLATFORM / 'accounts', EXTENSION / 'src', PROJECT / 'lumina' / 'src']
    for root in roots:
        for path in root.rglob('*'):
            if not path.is_file() or path.suffix not in ('.py', '.js', '.ts', '.tsx') or re.search(r'(^test_|\.test\.|/tests?/|/vendor/|/gen/|migrations/)', str(path)):
                continue
            for m in re.finditer(r"""(?:https?|wss?)://([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)""", path.read_text(errors='ignore')):
                host = m.group(1).lower()
                if host not in IGNORED_HOSTS and not host.endswith(('.test', '.invalid', '.example')) and not re.fullmatch(r'[\d.]+', host):
                    found.add(host)
    return sorted(found)


def assistant():
    """How the customer's assistant reaches the outside world, read from the cell wiring (lifecycle/cell_config.py): who gets its searches, which plugins and MCP servers it
    has, which tools are switched off, and which public DNS servers it uses. A new plugin, an outside MCP server or another search provider is a new recipient of what
    customers ask for, even when no URL for it appears anywhere in the code."""
    path = PLATFORM / 'agentai_platform' / 'lifecycle' / 'cell_config.py'
    text = _read(path)
    constants = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                constants[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, SyntaxError):
                pass
    plugins = set()
    for root in (PLATFORM / 'agentai_platform', PLATFORM / 'accounts'):
        for f in root.rglob('*.py'):
            if not re.search(r'(^test_|/tests?/)', str(f)):
                plugins |= set(re.findall(r"@openclaw/[a-z0-9-]+", f.read_text(errors='ignore')))
    search = re.findall(r"tools\.web\.search\.provider'\s*,\s*'([\w-]+)'", text)
    return {
        'search_provider': search[0] if search else None,
        'plugins': sorted(plugins),
        'mcp_servers': sorted({k.value for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Dict)
                               for key, value in zip(node.keys, node.values) if isinstance(key, ast.Constant) and key.value == 'servers' and isinstance(value, ast.Dict)
                               for k in value.keys if isinstance(k, ast.Constant)}),
        'tools_switched_off': sorted(constants.get('DENIED_TOOLS', ())),
        'dns_servers': sorted(constants.get('RESOLVERS', ())),
    }


def owner_only_ultrafast():
    """The experimental decider is the only path to OpenRouter; it must stay limited to the one account named in a root-owned file."""
    text = _read(PLATFORM / 'agentai_platform' / 'browse' / 'service_main.py')
    return 'account == owner' in text and 'ultrafast-owner' in text


def schema():
    """Every table and column that holds customer data: the foundation database (created fresh) and the account models (read from source, no Django needed)."""
    lines = []
    from agentai_platform.store import Store
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / 'db.sqlite3'); store.initialize()
        with store.connect() as con:
            for (table,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
                for col in con.execute(f'PRAGMA table_info("{table}")'):
                    lines.append(f'db.{table}.{col[1]}:{col[2].upper()}')
    tree = ast.parse(_read(PLATFORM / 'accounts' / 'models.py'))
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.Assign) and isinstance(item.value, ast.Call) and 'models.' in ast.unparse(item.value.func):
                    lines.append(f'accounts.{node.name}.{ast.unparse(item.targets[0])}:{ast.unparse(item.value.func).split(".")[-1]}')
    lines.sort()
    return {'count': len(lines), 'sha256': hashlib.sha256('\n'.join(lines).encode()).hexdigest(), 'lines': lines}


def everything(with_lines=False):
    s = schema()
    return {'retention': retention(), 'extension': extension(), 'assistant': assistant(), 'hosts': hosts(), 'owner_only_ultrafast': owner_only_ultrafast(),
            'schema': {'count': s['count'], 'sha256': s['sha256'], **({'lines': s['lines']} if with_lines else {})}}


if __name__ == '__main__':
    print(json.dumps(everything(with_lines='--lines' in sys.argv), indent=1))
