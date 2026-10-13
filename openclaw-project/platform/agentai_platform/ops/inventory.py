"""Recovery inventory: every asset, who owns it, how it is protected and how it comes back.

The monitor checks each asset against the newest complete backup set, so an asset without a
verified copy is visible as a gap instead of an assumption.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Asset:
    id: str
    what: str
    where: str
    owner: str
    method: str
    restore: str
    critical: bool = True
    backed_up_by: str = ''     # the BackupJob asset label; '' means documented but not copied (reason in `restore`)


ASSETS = (
    Asset('app-db', 'Customer application database: accounts, chats, memory, files metadata, usage ledger, entitlements, billing records',
          '/var/lib/agentai-platform/platform.sqlite3', 'owner', 'SQLite online backup (consistent while live), integrity-checked, age-encrypted',
          'Account-scoped restore into a new file (ops restore-account); swap in with the app stopped; billing reconciles with Stripe afterwards', backed_up_by='app-db'),
    Asset('custody-db', 'Supervisor custody and operation journal (cell bindings, fences)', '/var/lib/agentai-supervisor/custody.sqlite3', 'owner',
          'SQLite online backup, age-encrypted', 'Restore with the supervisor stopped; unresolved journal rows stay uncertain until reconciled', backed_up_by='custody-db'),
    Asset('tenant-cells', 'Per-customer cell state, workspaces, auth profiles, artifacts', '/var/lib/agentai-fleet/.openclaw/fleet (per-tenant capped volumes)',
          'owner', 'Fleet backup of each stopped cell by the lifecycle worker; newest archive per tenant packaged and encrypted separately',
          'Quarantined restore (separate cell, egress dropped); promote only after review', backed_up_by='tenant-cells'),
    Asset('customer-files', 'Files customers uploaded and files assistants made for them (immutable versions)', '/var/lib/agentai-platform/storage', 'owner',
          'Tar of the storage directory inside the encrypted set; metadata and hashes are in app-db', 'Extract beside the restored app-db with the app stopped; downloads verify against the stored hashes', backed_up_by='customer-files'),
    Asset('tenant-secrets', 'Per-tenant gateway tokens and provider key references', '/var/lib/agentai-supervisor-secrets', 'owner',
          'Tar of the custody directory inside the encrypted set (never plain, never in a tenant manifest)', 'Restore with the supervisor stopped; rotate keys after any host compromise', backed_up_by='tenant-secrets'),
    Asset('litellm-spend', 'Model proxy budget and spend database (virtual keys, spend history)', 'postgres volume (openclaw-production)', 'owner',
          'Nightly pg_dump by openclaw-ops-backup, then packaged and encrypted', 'psql restore into a fresh volume; keep LITELLM_SALT_KEY and master key', backed_up_by='litellm'),
    Asset('owner-state', 'Owner OpenClaw runtime: agents, sessions, workspace, plugins, config', '/opt/openclaw-production/openclaw-state', 'owner',
          'Native `backup create --verify` archive nightly, then packaged and encrypted', 'ops-restore.sh into an isolated clone; sanitize channels before any start', backed_up_by='owner-state'),
    Asset('config', 'Service configuration: compose, Caddy, systemd units, firewall, switches, billing files, app env, owner secrets',
          '/etc and /opt/openclaw-production', 'owner', 'Tar inside the encrypted set', 'Extract to a scratch dir, diff, then install selected files', backed_up_by='config'),
    Asset('versions', 'Pinned versions: release id, image digests, runtime and package versions', 'generated per run', 'owner',
          'JSON generated at backup time and included in the set', 'Reference when rebuilding a host', critical=False, backed_up_by='versions'),
    Asset('encryption-keys', 'Backup decryption identity (age private key)', 'owner password manager or offline copy, NEVER on the host', 'owner',
          'Held only by the owner; the host has the public recipient only', 'Without it every backup is unreadable: keep two copies in separate places', backed_up_by=''),
    Asset('stripe-state', 'Subscription and invoice truth', 'Stripe', 'Stripe', 'Provider-held; platform reconciles', 'billing_worker --reconcile after any restore', critical=False, backed_up_by=''),
    Asset('domain-dns', 'DNS records for getlumina.pro', 'DNS provider', 'owner', 'Provider-held', 'Re-point records to the new host', critical=False, backed_up_by=''),
)

BACKED_UP = tuple(a.backed_up_by for a in ASSETS if a.backed_up_by)


def gaps(manifest):
    """Assets the newest complete set did not cover."""
    covered = {a.get('asset') for a in manifest.get('artifacts', [])}
    return [a.id for a in ASSETS if a.backed_up_by and a.backed_up_by not in covered and (a.backed_up_by not in ('tenant-cells', 'customer-files') or covered & {a.backed_up_by})]
