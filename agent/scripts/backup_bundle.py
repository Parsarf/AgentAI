"""Encrypted, maintenance-window Postgres + state backup/restore.

Uses pg_dump/pg_restore for DB data, tar only for durable files, and the
already-pinned cryptography package for streaming AES-256-GCM encryption.
The passphrase and vault master key are separate external recovery secrets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"AGENTBK1"
CHUNK = 1024 * 1024
NAME = re.compile(r"^agent-backup-\d{8}T\d{6}Z-[0-9a-f]{8}\.abackup$")


def _run(args: list[str], *, env: dict | None = None) -> str:
    result = subprocess.run(args, check=False, text=True, capture_output=True, env=env)
    if result.returncode:
        raise ValueError(f"{args[0]} failed: {result.stderr[:700].strip()}")
    return result.stdout.strip()


def _passphrase() -> bytes:
    value = os.environ.get("BACKUP_PASSPHRASE", "")
    if len(value) < 16:
        raise ValueError("BACKUP_PASSPHRASE must be at least 16 characters")
    return value.encode()


def _key(passphrase: bytes, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _encrypt(source: Path, output: Path, passphrase: bytes) -> None:
    salt, nonce = os.urandom(16), os.urandom(12)
    cipher = Cipher(algorithms.AES(_key(passphrase, salt)), modes.GCM(nonce))
    encryptor = cipher.encryptor()
    with source.open("rb") as raw, output.open("xb") as sealed:
        sealed.write(MAGIC + salt + nonce)
        while block := raw.read(CHUNK):
            sealed.write(encryptor.update(block))
        sealed.write(encryptor.finalize())
        sealed.write(encryptor.tag)


def _decrypt(source: Path, output: Path, passphrase: bytes) -> None:
    size = source.stat().st_size
    if size < len(MAGIC) + 16 + 12 + 16:
        raise ValueError("backup is too short")
    with source.open("rb") as sealed:
        if sealed.read(len(MAGIC)) != MAGIC:
            raise ValueError("not an AgentAI encrypted backup")
        salt, nonce = sealed.read(16), sealed.read(12)
        sealed.seek(size - 16)
        tag = sealed.read(16)
        sealed.seek(len(MAGIC) + 28)
        decryptor = Cipher(algorithms.AES(_key(passphrase, salt)), modes.GCM(nonce, tag)).decryptor()
        remaining = size - (len(MAGIC) + 28 + 16)
        with output.open("xb") as raw:
            while remaining:
                block = sealed.read(min(CHUNK, remaining))
                if not block:
                    raise ValueError("truncated backup")
                remaining -= len(block)
                raw.write(decryptor.update(block))
            raw.write(decryptor.finalize())  # authentication failure raises


def _safe_dir(path: str, *, must_exist: bool) -> Path:
    target = Path(path).expanduser()
    if not target.is_absolute() or target.is_symlink() or target == Path("/"):
        raise ValueError("use an absolute, non-symlink directory path")
    if must_exist and not target.is_dir():
        raise ValueError(f"directory does not exist: {target}")
    if not must_exist and target.exists():
        raise ValueError(f"restore state target must not exist: {target}")
    return target


def _no_symlinks(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"symlink not allowed in backup state: {path}")
    if path.is_dir():
        for child in path.iterdir():
            _no_symlinks(child)


def _add_tree(archive: tarfile.TarFile, source: Path, label: str, hashes: dict[str, str]) -> None:
    archive.add(source, arcname=label, recursive=False)
    for child in sorted(source.rglob("*")):
        name = f"{label}/{child.relative_to(source).as_posix()}"
        archive.add(child, arcname=name, recursive=False)
        if child.is_file():
            hashes[name] = _sha(child)


def _db_name(dsn: str) -> str:
    parsed = urlparse(dsn)
    name = unquote(parsed.path.lstrip("/"))
    if (
        parsed.scheme not in ("postgres", "postgresql")
        or not parsed.hostname
        or not name
        or "/" in name
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("DATABASE_URL must identify one explicit PostgreSQL database")
    return name


def _pg_env(dsn: str) -> dict[str, str]:
    """Pass DB credentials via environment, never process arguments."""
    name = _db_name(dsn)
    parsed = urlparse(dsn)
    if not parsed.username:
        raise ValueError("database URL must include a role")
    env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG") if key in os.environ}
    env.update(
        {
            "PGHOST": parsed.hostname or "",
            "PGPORT": str(parsed.port or 5432),
            "PGUSER": unquote(parsed.username),
            "PGDATABASE": name,
        }
    )
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    return env


def backup(args: argparse.Namespace) -> Path:
    if not args.maintenance_confirmed:
        raise ValueError("stop app writes and pass --maintenance-confirmed")
    dsn = os.environ.get("DATABASE_URL", "")
    database = _db_name(dsn)
    pg_env = _pg_env(dsn)
    passphrase = _passphrase()
    output_dir = _safe_dir(args.output_dir, must_exist=True)
    skills = _safe_dir(args.skills_root, must_exist=True)
    profiles = _safe_dir(args.profiles_root, must_exist=True)
    if output_dir.resolve().is_relative_to(skills.resolve()) or output_dir.resolve().is_relative_to(
        profiles.resolve()
    ):
        raise ValueError("backup output must be outside durable state roots")
    _no_symlinks(skills)
    _no_symlinks(profiles)
    with tempfile.TemporaryDirectory(prefix="agent-backup-stage-", dir=output_dir) as stage_dir:
        stage = Path(stage_dir)
        dump = stage / "db.dump"
        _run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--file", str(dump)], env=pg_env)
        metadata = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "source_database": database,
            "vault_key_id": args.vault_key_id,
            "schema_version": _run(
                ["psql", "-Atc", "SELECT coalesce(max(version),0) FROM schema_migrations"], env=pg_env
            ),
            "counts": {},
            "sha256": {"db.dump": _sha(dump)},
        }
        for table in ("users", "tasks", "memories", "jobs", "vault_entries"):
            metadata["counts"][table] = int(
                _run(["psql", "-Atc", f"SELECT count(*) FROM {table}"], env=pg_env)
            )
        tar_path = stage / "bundle.tar"
        with tarfile.open(tar_path, "w") as archive:
            archive.add(dump, arcname="db.dump", recursive=False)
            _add_tree(archive, skills, "skills", metadata["sha256"])
            _add_tree(archive, profiles, "browser_profiles", metadata["sha256"])
            manifest = stage / "manifest.json"
            manifest.write_text(json.dumps(metadata, sort_keys=True, indent=2))
            archive.add(manifest, arcname="manifest.json", recursive=False)
        name = f"agent-backup-{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{os.urandom(4).hex()}.abackup"
        temporary = stage / name
        _encrypt(tar_path, temporary, passphrase)
        check = stage / "verified.tar"
        _decrypt(temporary, check, passphrase)
        if _sha(check) != _sha(tar_path):
            raise ValueError("backup verification failed")
        final = output_dir / name
        temporary.replace(final)
    if args.keep is not None:
        candidates = sorted(
            (p for p in output_dir.iterdir() if p.is_file() and NAME.fullmatch(p.name)),
            key=lambda p: p.name,
            reverse=True,
        )
        for old in candidates[args.keep :]:
            old.unlink()
    print(f"verified encrypted backup: {final} ({final.stat().st_size} bytes)")
    return final


def _extract_checked(archive_path: Path, destination: Path) -> dict:
    with tarfile.open(archive_path, "r") as archive:
        members = archive.getmembers()
        allowed = {"db.dump", "manifest.json", "skills", "browser_profiles"}
        for member in members:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or path.parts[0] not in allowed
                or not (member.isfile() or member.isdir())
            ):
                raise ValueError("unsafe backup archive member")
        for member in members:
            target = destination / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output)
    manifest = json.loads((destination / "manifest.json").read_text())
    if manifest.get("format") != 1 or not isinstance(manifest.get("sha256"), dict):
        raise ValueError("unsupported backup manifest")
    expected = manifest["sha256"]
    actual = {
        str(path.relative_to(destination)): _sha(path)
        for path in destination.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    if actual != expected:
        raise ValueError("backup checksum mismatch")
    return manifest


def restore(args: argparse.Namespace) -> None:
    dsn = os.environ.get("RESTORE_DATABASE_URL", "")
    name = _db_name(dsn)
    pg_env = _pg_env(dsn)
    app_name = _db_name(os.environ.get("DATABASE_URL", ""))
    if not name.endswith("_restore_test") or name == app_name:
        raise ValueError("restore database must be a separate *_restore_test database")
    state = _safe_dir(args.state_root, must_exist=False)
    temp_root = Path(tempfile.gettempdir()).resolve()
    if not state.parent.resolve().is_relative_to(temp_root):
        raise ValueError("restore state root must be under the system temp directory")
    bundle = Path(args.backup).resolve()
    if not bundle.is_file() or not NAME.fullmatch(bundle.name):
        raise ValueError("expected a named encrypted .abackup file")
    passphrase = _passphrase()
    existing = int(
        _run(
            [
                "psql",
                "-Atc",
                "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')",
            ],
            env=pg_env,
        )
    )
    if existing:
        raise ValueError("restore target database is not empty")
    with tempfile.TemporaryDirectory(prefix="agent-restore-stage-", dir=state.parent) as stage_dir:
        stage = Path(stage_dir)
        archive_path = stage / "bundle.tar"
        _decrypt(bundle, archive_path, passphrase)
        manifest = _extract_checked(archive_path, stage / "contents")
        if manifest.get("vault_key_id") != args.vault_key_id:
            raise ValueError("vault key identity does not match backup")
        _run(
            [
                "pg_restore",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                str(stage / "contents/db.dump"),
            ],
            env=pg_env,
        )
        for table, count in manifest["counts"].items():
            actual = int(_run(["psql", "-Atc", f"SELECT count(*) FROM {table}"], env=pg_env))
            if actual != count:
                raise ValueError(f"restored {table} count mismatch")
        state.mkdir(mode=0o700)
        for label in ("skills", "browser_profiles"):
            shutil.copytree(stage / "contents" / label, state / label)
    print(f"restored into disposable database {name} and {state}; verify vault with separate key")


def main(argv: list[str] | None = None) -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("backup")
    make.add_argument("--output-dir", required=True)
    make.add_argument("--skills-root", required=True)
    make.add_argument("--profiles-root", required=True)
    make.add_argument("--vault-key-id", required=True)
    make.add_argument("--maintenance-confirmed", action="store_true")
    make.add_argument("--keep", type=int, default=7)
    take = sub.add_parser("restore")
    take.add_argument("--backup", required=True)
    take.add_argument("--state-root", required=True)
    take.add_argument("--vault-key-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            if args.keep is not None and args.keep < 1:
                raise ValueError("--keep must be positive")
            backup(args)
        else:
            restore(args)
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError) as exc:
        print(f"{args.command} failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
