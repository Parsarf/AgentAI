"""Backup encryption and restore target guards (no live DB mutation)."""

from __future__ import annotations

import tarfile

import pytest
from cryptography.exceptions import InvalidTag

from scripts import backup_bundle as bundle


def test_encrypted_backup_round_trip_and_tamper_rejection(tmp_path):
    source = tmp_path / "plain"
    source.write_bytes(b"private data" * 1000)
    encrypted = tmp_path / "sealed"
    bundle._encrypt(source, encrypted, b"long recovery passphrase")
    assert b"private data" not in encrypted.read_bytes()
    restored = tmp_path / "restored"
    bundle._decrypt(encrypted, restored, b"long recovery passphrase")
    assert restored.read_bytes() == source.read_bytes()
    corrupt = bytearray(encrypted.read_bytes())
    corrupt[-20] ^= 1
    encrypted.write_bytes(corrupt)
    with pytest.raises(InvalidTag):
        bundle._decrypt(encrypted, tmp_path / "invalid", b"long recovery passphrase")


def test_archive_refuses_traversal_and_symlink(tmp_path):
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as tar:
        info = tarfile.TarInfo("skills/../../outside")
        info.size = 0
        tar.addfile(info)
    with pytest.raises(ValueError, match="unsafe"):
        bundle._extract_checked(archive, tmp_path / "extract")


@pytest.mark.parametrize(
    "dsn",
    [
        "postgresql://agent@localhost/",
        "postgresql://agent@localhost/a/b",
        "postgresql://agent@localhost/agent?host=/tmp",
        "sqlite:///test",
    ],
)
def test_database_target_must_be_explicit(dsn):
    with pytest.raises(ValueError):
        bundle._db_name(dsn)
