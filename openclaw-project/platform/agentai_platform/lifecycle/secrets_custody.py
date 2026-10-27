"""Host-side secret custody for customer cells.

Per-tenant Gateway tokens and provider virtual keys are generated and held here,
never in the app database, a claim, a receipt or an audit row. The directory is
host-owned and private; files are created exclusively with mode 0600 and read
back only by the supervisor. A cell receives only its own two values. Another
tenant's secrets, the owner's keys and the LiteLLM master key are never passed
into a cell. Provider keys are issued with an independent budget so a cell
cannot spend beyond its allowance even if the platform ledger is bypassed.
"""
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import stat

TENANT = re.compile(r'aa-[a-f0-9]{32}')
TOKEN = re.compile(r'[A-Za-z0-9_.-]{16,256}')


class CustodyError(Exception): pass


class SecretStore:
    def __init__(self, root, *, owner_uid=None):
        self.root = Path(root)
        self.owner_uid = os.geteuid() if owner_uid is None else owner_uid
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._private(self.root, directory=True)

    def _private(self, path, *, directory=False):
        info = path.lstat()
        if info.st_uid != self.owner_uid or stat.S_IMODE(info.st_mode) & 0o077:
            raise CustodyError('secret custody must be private and host-owned')
        if directory and not stat.S_ISDIR(info.st_mode):
            raise CustodyError('unsafe custody path')
        if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
            raise CustodyError('unsafe custody path')

    def _dir(self, tenant, create=False):
        if type(tenant) is not str or not TENANT.fullmatch(tenant):
            raise CustodyError('invalid tenant')
        path = self.root / tenant
        if create:
            path.mkdir(mode=0o700, exist_ok=True)
        if path.exists():
            self._private(path, directory=True)
        return path

    def _read(self, tenant, name):
        path = self._dir(tenant) / name
        try:
            self._private(path)
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        with os.fdopen(fd) as handle:
            value = handle.read().strip()
        if not TOKEN.fullmatch(value):
            raise CustodyError('corrupt secret')
        return value

    def _create(self, tenant, name, value):
        if not TOKEN.fullmatch(value):
            raise CustodyError('invalid secret value')
        path = self._dir(tenant, create=True) / name
        # O_EXCL: a concurrent or repeated creation can never overwrite a secret.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(value + '\n')

    def gateway_token(self, tenant):
        """Same token on every call for the life of the tenant; created on first use."""
        value = self._read(tenant, 'gateway-token')
        if value is None:
            try:
                self._create(tenant, 'gateway-token', secrets.token_hex(32))
            except FileExistsError:
                pass
            value = self._read(tenant, 'gateway-token')
        return value

    def provider_key(self, tenant):
        return self._read(tenant, 'provider-key')

    def store_provider_key(self, tenant, key):
        if self.provider_key(tenant) is not None:
            raise CustodyError('provider key already issued')
        self._create(tenant, 'provider-key', key)

    def replace_provider_key(self, tenant, key):
        """Atomic swap used by rotation: the new key is durable before the old one is revoked."""
        if not TOKEN.fullmatch(key): raise CustodyError('invalid secret value')
        directory = self._dir(tenant, create=True)
        tmp = directory / 'provider-key.new'
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as handle: handle.write(key + '\n')
        os.replace(tmp, directory / 'provider-key')

    def destroy(self, tenant):
        """Remove exactly this tenant's secrets (delete and retention purge)."""
        path = self._dir(tenant)
        if path.exists():
            shutil.rmtree(path)


class ProviderKeys:
    """Issues and revokes per-tenant virtual keys on the model proxy (LiteLLM API).

    `http(method, path, body)` is injected and authenticated with the master key
    by the host; it returns (status, decoded_json). The master key never reaches
    a cell, this class's return values, or logs.
    """

    def __init__(self, http, store):
        self.http, self.store = http, store

    def issue(self, tenant, account_id, *, max_budget_usd, duration_days, models, rpm_limit=30, tpm_limit=200_000):
        if not isinstance(max_budget_usd, (int, float)) or isinstance(max_budget_usd, bool) \
                or not 0 < max_budget_usd <= 1000:
            raise CustodyError('invalid key budget')
        if type(duration_days) is not int or not 1 <= duration_days <= 400:
            raise CustodyError('invalid key duration')
        if type(models) is not list or not models or not all(type(m) is str and m for m in models):
            raise CustodyError('explicit model allowlist required')
        for limit in (rpm_limit, tpm_limit):   # per-key provider rate limits bound a runaway agent independently of the ledger
            if type(limit) is not int or isinstance(limit, bool) or limit < 1: raise CustodyError('invalid provider rate limit')
        if self.store.provider_key(tenant) is not None:
            return False  # idempotent: a retry reuses the key already in custody
        status, body = self.http('POST', '/key/generate', {
            'key_alias': tenant, 'max_budget': max_budget_usd, 'duration': f'{duration_days}d',
            'models': models, 'rpm_limit': rpm_limit, 'tpm_limit': tpm_limit, 'metadata': {'account_id': account_id, 'tenant': tenant}})
        key = body.get('key') if isinstance(body, dict) else None
        if status != 200 or type(key) is not str:
            raise CustodyError('provider key issuance failed')
        self.store.store_provider_key(tenant, key)
        return True

    def ensure_models(self, tenant, models):
        """Make the tenant's key allow exactly `models` (idempotent). A tenant with no key in custody is left alone."""
        if type(models) is not list or not models or not all(type(m) is str and m for m in models):
            raise CustodyError('explicit model allowlist required')
        key = self.store.provider_key(tenant)
        if key is None:
            return False
        status, _ = self.http('POST', '/key/update', {'key': key, 'models': models})
        if status != 200:
            raise CustodyError('provider key update failed')
        return True

    def revoke(self, tenant):
        key = self.store.provider_key(tenant)
        if key is None:
            return False
        status, _ = self.http('POST', '/key/delete', {'keys': [key]})
        if status != 200:
            raise CustodyError('provider key revocation failed')
        return True
