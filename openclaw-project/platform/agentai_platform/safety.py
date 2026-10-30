"""Safety switches (stdlib only, so the worker and browse service can import it).

Every safety feature has a key here and is ON unless a row in `safety_overrides` says otherwise. A feature is only ever checked through
`is_on`, which fails closed: a missing table, an unreadable row or any error means "on".

Two scopes. A row for an account changes that account only; a row under `ALL` ("*", never an account id) is the default for every account. For one account the
MORE SPECIFIC setting wins: its own row (off, or an explicit "on" that exempts it from an "off" for everyone), else the all-users row, else on. An "off" row that
has expired counts as no row.

Who may open the menu is decided by accounts/safety.py: the owner account named in `AGENTAI_SAFETY_OWNER_ACCOUNT`, plus any account the owner has granted access
(`safety_access`). Granted accounts see and change only their own switches; only the owner sees the all-users scope or the grants. This module does not decide who may.

`wired` says whether a gate in the code actually reads the switch. A switch with `wired=False` is stored and shown but changes nothing yet,
and the page says so; it never pretends to be enforced. `kind` says what a switch is: `gate` (a rule the code can skip for an account), `shared` (server-wide, set in
deploy files or at the provider: shown, never switched here) or `core` (a protection that is never switched off from the menu). `privacy` marks the protections that
keep customer data from leaking: they can be switched off for your own account but never for everyone.
"""
from __future__ import annotations
import json
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Feature:
    key: str
    group: str
    title: str
    plain: str
    wired: bool = False
    kind: str = 'gate'            # gate | shared | core
    privacy: bool = False         # protects customer data: never switched off for everyone


ALL = '*'                        # the all-users scope: not an account id (those are 32 hex characters)


class Locked(Exception):
    """The switch cannot be changed here. `reason`: 'shared' | 'core' | 'privacy'."""
    def __init__(self, reason):
        super().__init__(reason); self.reason = reason


GROUPS = (('platform', 'Lumina platform'), ('browser', 'Browser'), ('data', 'Data and privacy'), ('injection', 'Prompt-injection defenses'), ('limits', 'Input limits and validation'), ('access', 'Sign-in and sessions'), ('openclaw', 'OpenClaw assistants'), ('server', 'Server hardening'), ('core', 'Core protections'))

FEATURES: dict[str, Feature] = {f.key: f for f in (
    Feature('budget_caps', 'platform', 'Spending caps', 'The per-task, daily and monthly limits and the money reservation before a task starts.', True),
    Feature('standard_browser', 'browser', 'Use the standard Lumina browser', 'Browser tasks run in the sandboxed stage with a clean profile every time. Switch OFF (your own account, with a time limit) to test the experimental jev-ultrafast browser instead.', True),
    Feature('queue_limit', 'platform', 'Queue limit', 'At most 3 tasks waiting per account; a fourth is refused until one starts.', True),
    Feature('rate_limits', 'platform', 'Request rate limits', 'Per-account limits on how often routes can be called.', True),
    Feature('routing_policy', 'platform', 'Routing policy gates', 'Rules that can refuse or reshape how a request runs. Not in the live request path yet, so nothing reads this switch.'),
    Feature('confirmations', 'platform', 'Confirmations and notices', 'Terms and cost acknowledgements before a feature is used. The current app does not show any, so nothing reads this switch.'),
    Feature('payment_stop', 'browser', 'Stop at payment pages', 'The browser hands the screen back at any payment step.', True),
    Feature('sensitive_approval', 'browser', 'Approval for sensitive clicks', 'Pay, delete, send and password controls need your approval.', True),
    Feature('denied_sites', 'browser', 'Denied sites and human-check stops', 'Banking and trading sites the browser refuses, and stopping at captchas and sign-in pages.', True),
    Feature('personal_data_scrub', 'data', 'Scrub personal data before third parties', 'Emails, numbers, keys and addresses removed from the page text and labels sent to the browser model (JEV).', True),
    Feature('vault_notice', 'data', 'Saved-login notice and no card codes', 'The notice before saving a login or card. A card security code is never stored, whatever this says.', True),
    Feature('secret_redaction', 'data', 'Secret redaction in Activity and logs', 'Keys and tokens hidden in the event records the app stores. The tool-call summaries in the Activity window are always redacted.', True),
    Feature('ssrf_guard', 'data', 'Network destination guard (SSRF)', 'Stops the assistant\'s browser reaching private addresses and cloud metadata endpoints. The network firewall around every assistant always applies.', True),
    Feature('untrusted_page_text', 'injection', 'Treat web page text as untrusted', 'Page text is neutralised before the assistant reads it, so a page cannot give it orders.', True),
    Feature('assistant_output_cleaning', 'injection', 'Clean the assistant\'s plans and choices', 'The task, steps, search terms and choices the assistant sends to the browser are length-limited and neutralised before they are used. Plans in chat are always cleaned.', True),
    Feature('message_length_limit', 'limits', 'Message length limit', 'Messages over 16,000 characters are refused. The database enforces this too, so it is not a switch.'),
    Feature('project_chat_limits', 'limits', 'Project and conversation limits', 'At most 10 projects per account and 100 conversations per project.', True),
    Feature('upload_limits', 'limits', 'File upload limits', 'Size and count limits on uploaded files (10 MiB a file; 25 MiB and 10 files a batch). The content checks always apply.', True),
    Feature('block_validation', 'limits', 'Validation of generated UI blocks', 'Cards, tables and plans the assistant makes must match a fixed schema. Always on: the code builds on the checked result.'),
    Feature('login_limits', 'access', 'Sign-in attempt limits', 'Limits on password tries per address and per network.'),
    Feature('csrf_protection', 'access', 'CSRF protection', 'Writes must carry the page\'s secret token.'),
    Feature('session_epochs', 'access', 'Session revocation', 'Sessions end when a password changes or an account is revoked. Always on.'),
    Feature('operator_mfa', 'access', 'Operator two-step sign-in and grants', 'Operators need a second step and a time-limited grant for each action.'),
    Feature('unit_sandboxing', 'server', 'Service sandboxing (systemd)', 'The limits the server places on each Lumina service. Set in deploy files on the server, not in the app.'),
    Feature('cell_container_isolation', 'server', 'Assistant container isolation (Docker)', 'Each assistant runs in its own container with no host access. Set on the server.'),
    Feature('proxy_rules', 'server', 'Web proxy rules (Caddy)', 'Which paths are public and which headers are set. Set on the server.'),
    Feature('provider_backstops', 'server', 'Provider-side spending caps', 'The daily and monthly caps set on the model provider keys. Set at the provider.'),
    Feature('tool_ceilings', 'openclaw', 'Tool ceilings per agent', 'Stops the assistant using the cell\'s browser tool directly: it must go through Lumina\'s browser rules. The runtime\'s own tool limits are set by the fleet profile.', True),
    Feature('web_limits', 'openclaw', 'Web access limits per agent', 'Which agents may fetch, search or browse. Each assistant has one agent today, so nothing reads this switch.'),
    Feature('cell_limits', 'openclaw', 'Cell sandbox and resource limits', 'Memory, CPU, filesystem and network limits on your assistant cell. They protect the whole host, so they are set on the server.'),
    Feature('screenshot_retention', 'data', 'Delete browser screenshots after a day', 'Pages can show personal data, so the browser service deletes its screenshots a day after the task.', True),
    Feature('bridge_restrictions', 'server', 'Assistant bridge restrictions', 'The fixed list of calls, the root-only browser access and the named page scripts on the cell bridge. Set in code.'),
    Feature('cell_key_limits', 'server', 'Per-assistant model key limits', 'Requests and tokens per minute on each assistant\'s model key. Set when the key is issued.'),
    Feature('cell_firewall', 'server', 'Assistant network firewall', 'Keeps every assistant off private networks and other assistants. Set on the server.'),
    Feature('tenant_isolation', 'core', 'Tenant isolation', 'Keeps each account\'s data separate from every other account.'),
    Feature('vault_encryption', 'core', 'Vault encryption', 'Encryption of saved logins, cards and provider keys.'),
    Feature('audit_log', 'core', 'Audit log', 'A record of sensitive actions.'),
)}


# What each switch is. Server-wide protections cannot be switched for one account; the core ones are never switched off from the menu; the privacy ones can be
# switched off for your own account but never for everyone.
SHARED = {'login_limits', 'csrf_protection', 'operator_mfa', 'unit_sandboxing', 'cell_container_isolation', 'proxy_rules', 'provider_backstops',
          'message_length_limit', 'cell_limits', 'bridge_restrictions', 'cell_key_limits', 'cell_firewall'}
CORE = {'tenant_isolation', 'vault_encryption', 'audit_log', 'session_epochs', 'block_validation'}
PRIVACY = {'personal_data_scrub', 'vault_notice', 'secret_redaction', 'ssrf_guard', 'screenshot_retention', 'standard_browser'}
FEATURES = {k: replace(f, kind='shared' if k in SHARED else 'core' if k in CORE else 'gate', privacy=k in PRIVACY) for k, f in FEATURES.items()}


def lock_of(feature: Feature, scope: str) -> str | None:
    """Why a switch cannot be changed in this scope (None = it can). `scope` is 'mine' or 'all'."""
    if feature.kind != 'gate':
        return feature.kind
    return 'privacy' if scope == 'all' and feature.privacy else None


def _state(row, now: float) -> bool | None:
    """What one row says: True (on), False (off), or None (no row, or an "off" that has expired: it says nothing)."""
    if row is None:
        return None
    enabled, expires = row[0], row[1]
    if enabled:
        return True
    return None if expires and now >= expires else False


def effective(own, inherited, now: float) -> bool:
    """The more specific setting wins: the account's own row, else the all-users row, else on."""
    for row in (own, inherited):
        state = _state(row, now)
        if state is not None:
            return state
    return True


def is_on(con, account_id: str, feature: str, now: float | None = None) -> bool:
    """True unless `feature` is switched off for this account, by its own row or by the all-users row (and the switch has not expired). Fails closed."""
    try:
        if feature not in FEATURES:
            return True
        now = now if now is not None else time.time()
        sql = 'SELECT enabled, expires_epoch FROM safety_overrides WHERE account_id=? AND feature=?'
        own = con.execute(sql, (account_id, feature)).fetchone() if account_id != ALL else None
        return effective(own, con.execute(sql, (ALL, feature)).fetchone(), now)
    except Exception:
        return True


def listing(con, account_id: str, now: float | None = None) -> list[dict]:
    """"My account": each switch as it applies to this account. `source` says where the setting comes from: 'account' (its own row), 'all' (the
    all-users row) or 'default' (nothing set)."""
    now = now if now is not None else time.time()
    rows = {(r[0], r[1]): (r[2], r[3]) for r in con.execute(
        'SELECT account_id, feature, enabled, expires_epoch FROM safety_overrides WHERE account_id IN (?, ?)', (account_id, ALL))}
    out = []
    for f in FEATURES.values():
        own, inherited = rows.get((account_id, f.key)), rows.get((ALL, f.key))
        mine, everyone = _state(own, now), _state(inherited, now)
        on = effective(own, inherited, now)
        source = 'account' if mine is not None else 'all' if everyone is not None else 'default'
        expires = None if on else (own if mine is not None else inherited)[1]
        out.append({'key': f.key, 'group': f.group, 'title': f.title, 'plain': f.plain, 'wired': f.wired, 'on': on,
                    'expires_epoch': expires, 'source': source, 'lock': lock_of(f, 'mine')})
    return out


def listing_all(con, now: float | None = None) -> list[dict]:
    """"All users": each switch's default for every account, and how many accounts have their own setting that differs from or exempts them from it."""
    now = now if now is not None else time.time()
    rows = {r[0]: (r[1], r[2]) for r in con.execute('SELECT feature, enabled, expires_epoch FROM safety_overrides WHERE account_id=?', (ALL,))}
    own = {r[0]: r[1] for r in con.execute(
        'SELECT feature, COUNT(*) FROM safety_overrides WHERE account_id<>? AND (enabled=1 OR expires_epoch IS NULL OR expires_epoch>?) GROUP BY feature', (ALL, int(now)))}
    out = []
    for f in FEATURES.values():
        row = rows.get(f.key)
        on = effective(None, row, now)
        out.append({'key': f.key, 'group': f.group, 'title': f.title, 'plain': f.plain, 'wired': f.wired, 'on': on,
                    'expires_epoch': None if on else row[1], 'source': 'all' if _state(row, now) is not None else 'default',
                    'lock': lock_of(f, 'all'), 'overridden': own.get(f.key, 0)})
    return out


def check_changeable(feature: str, on: bool, everyone: bool):
    """Raises KeyError (unknown switch) or Locked (cannot be changed in this scope). Callers check every requested change before writing any of them."""
    reason = lock_of(FEATURES[feature], 'all' if everyone else 'mine')
    if reason and not (reason == 'privacy' and on):          # a privacy protection can always be switched back ON, never off for everyone
        raise Locked(reason)


def set_feature(con, account_id: str, feature: str, on: bool, actor: str, *, expires_epoch: int | None = None, now: float | None = None):
    """Switch `feature` for one account, or for everyone when `account_id` is ALL. Raises KeyError (unknown) or Locked (cannot be changed here)."""
    check_changeable(feature, on, account_id == ALL)
    now = int(now if now is not None else time.time())
    if on:
        # "On" for an account removes its own row, unless everyone's default is currently off: then it keeps an explicit "on" so this account stays exempt.
        everyone = con.execute('SELECT enabled, expires_epoch FROM safety_overrides WHERE account_id=? AND feature=?', (ALL, feature)).fetchone()
        if account_id != ALL and _state(everyone, now) is False:
            con.execute('INSERT OR REPLACE INTO safety_overrides(account_id,feature,enabled,changed_by,changed_epoch,expires_epoch) VALUES (?,?,1,?,?,NULL)',
                        (account_id, feature, actor, now))
        else:
            con.execute('DELETE FROM safety_overrides WHERE account_id=? AND feature=?', (account_id, feature))
    else:
        con.execute('INSERT OR REPLACE INTO safety_overrides(account_id,feature,enabled,changed_by,changed_epoch,expires_epoch) VALUES (?,?,0,?,?,?)',
                    (account_id, feature, actor, now, expires_epoch))


# -- who else may open the menu (granted by the owner) ------------------------------------------------------------------------------------------------
def has_access(con, account_id: str) -> bool:
    try:
        return con.execute('SELECT 1 FROM safety_access WHERE account_id=?', (account_id,)).fetchone() is not None
    except Exception:
        return False                                   # fails closed: no table, no access


def grant_access(con, account_id: str, granted_by: str, now: float | None = None):
    con.execute('INSERT OR REPLACE INTO safety_access(account_id, granted_by, granted_epoch) VALUES (?,?,?)', (account_id, granted_by, int(now if now is not None else time.time())))


def revoke_access(con, account_id: str):
    con.execute('DELETE FROM safety_access WHERE account_id=?', (account_id,))
    con.execute('DELETE FROM safety_overrides WHERE account_id=?', (account_id,))     # a revoked account keeps none of the settings it made


def access_list(con) -> list[tuple[str, int]]:
    return [(r[0], r[1]) for r in con.execute('SELECT account_id, granted_epoch FROM safety_access ORDER BY granted_epoch')]


SNAPSHOT_VERSION = 1


def export_snapshot(con, path) -> None:
    """Write every switch setting to a small JSON file that other processes read (the browse service, the supervisor): they never open the app's database, which another user owns.
    Written whole and swapped in atomically, readable by the app's group. Expiry is judged by the reader from the stored time, so nothing has to be rewritten when an "off" lapses."""
    rows = [{'account': r[0], 'feature': r[1], 'enabled': int(bool(r[2])), 'expires': r[3]}
            for r in con.execute('SELECT account_id, feature, enabled, expires_epoch FROM safety_overrides')]
    path = Path(path)
    tmp = path.with_name(path.name + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o640)
    with os.fdopen(fd, 'w') as handle:
        handle.write(json.dumps({'version': SNAPSHOT_VERSION, 'written': int(time.time()), 'rows': rows}, separators=(',', ':')))
    os.replace(tmp, path)


class Reader:
    """For a process with no database connection of its own: reads the snapshot the app writes (`export_snapshot`). The file is read again whenever it changes, so a switch changed
    in the menu is seen at the next decision. Fails closed: a missing or unreadable file means every switch is on."""
    def __init__(self, path):
        self.path = str(path)
        self._stamp, self._rows = None, {}

    def _load(self):
        try:
            st = os.stat(self.path)
            stamp = (st.st_mtime_ns, st.st_size)
            if stamp != self._stamp:
                data = json.loads(Path(self.path).read_text())
                rows = {}
                if isinstance(data, dict) and data.get('version') == SNAPSHOT_VERSION:
                    for r in data.get('rows') or []:
                        rows[(r['account'], r['feature'])] = (r['enabled'], r['expires'])
                self._rows, self._stamp = rows, stamp
        except Exception:
            self._rows, self._stamp = {}, None
        return self._rows

    def on(self, account_id: str, feature: str, now: float | None = None) -> bool:
        try:
            if feature not in FEATURES:
                return True
            rows = self._load()
            now = now if now is not None else time.time()
            own = rows.get((account_id, feature)) if account_id != ALL else None
            return effective(own, rows.get((ALL, feature)), now)
        except Exception:
            return True

    def for_account(self, account_id: str):
        """A callable `switch(feature) -> bool` bound to one account."""
        return lambda feature: self.on(account_id, feature)
