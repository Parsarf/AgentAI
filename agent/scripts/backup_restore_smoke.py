"""One disposable encrypted backup/restore proof; never touches app data.

Requires a local admin DATABASE_URL able to create/drop databases, plus the
existing VAULT_MASTER_KEY. Creates random *_test databases and drops only the
names it created after verification. No external model or payment calls.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlparse, urlunparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import auth, db, secrets_vault, skills  # noqa: E402
from core.config import settings  # noqa: E402
from scripts.backup_bundle import _db_name, _pg_env  # noqa: E402


def _dsn_with_name(dsn: str, name: str) -> str:
    parsed = urlparse(dsn)
    return urlunparse(parsed._replace(path=f"/{name}"))


async def _seed(dsn: str, skills_root: Path) -> dict:
    await db.init_db(dsn)
    skills.SKILLS_ROOT = skills_root
    alice = await db.create_user(
        "restore-alice@example.test", auth._hash_password("test-only-password"), status="active"
    )
    bob = await db.create_user(
        "restore-bob@example.test", auth._hash_password("test-only-password"), status="active"
    )
    memory = await db.add_memory(alice.id, "known private memory", "fact", [0.01] * 384)
    await db.add_memory(bob.id, "bob private memory", "fact", [0.02] * 384)
    await db.log_api_cost(alice.id, None, "smoke", 10, 2, Decimal("0.001"))
    await secrets_vault.store_credential(str(alice.id), "canary.example", "alice-vault-canary")
    await secrets_vault.store_credential(str(bob.id), "canary.example", "bob-vault-canary")
    await skills.save_skill(
        str(alice.id), "restore-proof", "restore proof playbook", {}, "safe",
        {"instructions.md": "The private restore playbook."},
    )
    await db.close_pool()
    return {"alice": alice.id, "bob": bob.id, "memory": memory.id}


async def _verify(dsn: str, state_root: Path, saved: dict) -> None:
    await db.open_pool(dsn, force=True)
    skills.SKILLS_ROOT = state_root / "skills"
    try:
        assert await db.get_user(saved["alice"]) is not None
        assert await db.get_user(saved["bob"]) is not None
        assert await db.get_memory(saved["alice"], saved["memory"]) is not None
        assert await db.get_memory(saved["bob"], saved["memory"]) is None
        own = await secrets_vault.get_credential(str(saved["alice"]), "canary.example")
        other = await secrets_vault.get_credential(str(saved["bob"]), "canary.example")
        assert own is not None and own.reveal() == "alice-vault-canary"
        assert other is not None and other.reveal() == "bob-vault-canary"
        assert await skills.load_skill(str(saved["alice"]), "restore-proof") is not None
        assert await skills.load_skill(str(saved["bob"]), "restore-proof") is None
        assert (state_root / "browser_profiles" / str(saved["alice"]) / "session.txt").is_file()
    finally:
        await db.close_pool()


def main() -> int:
    if not settings.secrets.vault_master_key:
        print("VAULT_MASTER_KEY is required for a complete restore proof", file=sys.stderr)
        return 2
    app_dsn = settings.secrets.database_url
    app_name = _db_name(app_dsn)
    token = secrets.token_hex(4)
    source_name = f"agent_phase7_{token}_test"
    target_name = f"agent_phase7_{token}_restore_test"
    assert app_name not in (source_name, target_name)
    source_dsn = _dsn_with_name(app_dsn, source_name)
    target_dsn = _dsn_with_name(app_dsn, target_name)
    admin_env = _pg_env(app_dsn)
    created = []
    start = time.monotonic()
    try:
        for name in (source_name, target_name):
            subprocess.run(["createdb", "--maintenance-db=postgres", name],
                           env=admin_env, check=True, capture_output=True)
            created.append(name)
        with tempfile.TemporaryDirectory(prefix="agent-phase7-proof-") as directory:
            root = Path(directory)
            skills_root = root / "skills"
            profiles = root / "browser_profiles"
            backups = root / "backups"
            for folder in (skills_root, profiles, backups):
                folder.mkdir()
            saved = asyncio.run(_seed(source_dsn, skills_root))
            browser_state = profiles / str(saved["alice"])
            browser_state.mkdir()
            (browser_state / "session.txt").write_text("disposable session canary")
            secret = secrets.token_urlsafe(36)
            env = dict(os.environ)
            env.update({
                "DATABASE_URL": source_dsn, "BACKUP_PASSPHRASE": secret,
                "PYTHON_BIN": sys.executable,
            })
            backup_start = time.monotonic()
            subprocess.run([
                "bash", str(ROOT / "scripts/backup.sh"),
                "--output-dir", str(backups), "--skills-root", str(skills_root),
                "--profiles-root", str(profiles), "--vault-key-id", "smoke-vault-root",
                "--maintenance-confirmed", "--keep", "1",
            ], env=env, check=True)
            backup_seconds = time.monotonic() - backup_start
            bundle = next(backups.glob("agent-backup-*.abackup"))
            restore_state = root / "restored_state"
            env["DATABASE_URL"] = app_dsn
            env["RESTORE_DATABASE_URL"] = target_dsn
            restore_start = time.monotonic()
            subprocess.run([
                "bash", str(ROOT / "scripts/restore.sh"),
                "--backup", str(bundle), "--state-root", str(restore_state),
                "--vault-key-id", "smoke-vault-root",
            ], env=env, check=True)
            restore_seconds = time.monotonic() - restore_start
            asyncio.run(_verify(target_dsn, restore_state, saved))
            print(
                f"verified: 2 users, owner-scoped memory/vault/skill, browser state; "
                f"backup_bytes={bundle.stat().st_size} backup_s={backup_seconds:.2f} "
                f"restore_s={restore_seconds:.2f} total_s={time.monotonic()-start:.2f}"
            )
        return 0
    finally:
        for name in reversed(created):
            subprocess.run(["dropdb", "--maintenance-db=postgres", name],
                           env=admin_env, check=True, capture_output=True)


if __name__ == "__main__":
    raise SystemExit(main())
