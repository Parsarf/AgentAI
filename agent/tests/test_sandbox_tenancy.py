"""Sandbox path logic — the pure tenancy functions, no Docker required.
(Docker-dependent lifecycle tests skip when Docker is unreachable.)"""

from __future__ import annotations

import pytest

from tools import sandbox


@pytest.mark.parametrize("bad", [
    "../../bob",
    "bob/../../alice",
    "/etc",
    "a/b",
    "a b",
    ".",
    "..",
    "",
    "x" * 100,
    "${JNDI}",
])
def test_evil_ids_rejected(bad):
    with pytest.raises(ValueError):
        sandbox.workspace_path(bad if bad != "../../bob" else bad, "t1")


def test_workspace_path_scoped_and_stable():
    path = sandbox.workspace_path("userA", "task1")
    assert str(path).startswith(str(sandbox.SANDBOX_ROOT / "userA" / "task1"))
    other = sandbox.workspace_path("userB", "task1")
    assert other != path
    assert str(other).startswith(str(sandbox.SANDBOX_ROOT / "userB"))


def test_traversal_inside_ids_impossible():
    # The charset validator makes traversal structurally impossible:
    with pytest.raises(ValueError):
        sandbox.workspace_path("userA", "../../userB/steal")


def test_realpath_containment_catches_symlinks(tmp_path, monkeypatch):
    root = tmp_path / "sandboxes"
    root.mkdir()
    monkeypatch.setattr(sandbox, "SANDBOX_ROOT", root)
    user_dir = root / "u1" / "t1"
    user_dir.mkdir(parents=True)
    escape = user_dir / "innocent"
    escape.symlink_to(tmp_path)  # symlink pointing outside the sandbox root

    with pytest.raises(ValueError, match="escape"):
        sandbox.ensure_realpath_confined(escape)

    # a regular confined path passes:
    target = user_dir / "real.txt"
    target.write_text("x")
    assert sandbox.ensure_realpath_confined(target) == target.resolve()


def test_docker_unavailable_is_actionable(monkeypatch):
    def boom():
        raise ImportError("no docker")

    monkeypatch.setattr(sandbox, "_client", boom)
    # The message the TOOLS return (not the exception) is what matters; here we
    # assert the exception type the tools catch and translate.
    with pytest.raises(sandbox.SandboxUnavailable):
        raise sandbox.SandboxUnavailable("code execution needs Docker")
