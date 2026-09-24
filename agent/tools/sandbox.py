"""Where the agent writes and runs code — isolated per USER, not just per task.

Tenant isolation specifics (spec-mandated, test-covered):
- Each user's containers run on a per-user Docker network with no route to
  other users' containers or the host's internal services.
- Each user's workspace lives under /data/sandboxes/<user_id>/<task_id>/ and
  the mount logic refuses to construct a path outside that prefix regardless
  of what a task_id looks like (id charset enforced + realpath containment).
- Containers get network egress (their own network) but NO env vars, NO
  secrets, NO host filesystem access beyond their mounted workspace.
- Containers are destroyed at task end; workspaces are kept briefly for
  debugging and purged on a schedule (the retention sweep in main.py).

Docker is required at runtime. Without it the tools fail with an actionable
message; unit tests exercise the pure path logic without Docker.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Any

from core.config import settings
from core.logging import get_logger
from tools.base import ToolResult, tool

logger = get_logger(__name__)

SANDBOX_ROOT = Path("/data/sandboxes")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_IMAGE = "agent-sandbox:latest"
_LANGS = {"python": ("python3", ".py"), "javascript": ("node", ".js")}

_docker = None


class SandboxUnavailable(Exception):
    """Docker is not reachable — the tool surfaces this to the user."""


def _client():
    global _docker
    if _docker is None:
        try:
            import docker as docker_sdk

            _docker = docker_sdk.from_env()
            _docker.ping()
        except Exception as exc:
            raise SandboxUnavailable(
                "code execution needs Docker, which is not reachable on this host. "
                "Install Docker Desktop (or colima) and rebuild the agent-sandbox "
                "image: docker build -t agent-sandbox:latest -f sandbox/Dockerfile ."
            ) from exc
    return _docker


# --------------------------------------------------------------------------- #
# Pure path logic (unit-tested without Docker)
# --------------------------------------------------------------------------- #


def validate_id(value: str, kind: str) -> str:
    """Only [A-Za-z0-9_-] ids — kills traversal, absolute paths, separators."""
    if not isinstance(value, str) or not _SAFE_ID.match(value):
        raise ValueError(f"unsafe {kind} id: {value!r}")
    return value


def workspace_path(user_id: str, task_id: str) -> Path:
    """The ONLY way a workspace path is ever constructed."""
    uid = validate_id(user_id, "user")
    tid = validate_id(task_id, "task")
    root = SANDBOX_ROOT.resolve()
    path = (root / uid / tid).resolve()
    if not str(path).startswith(str(root) + os.sep):
        raise ValueError(f"path escaped sandbox root: {path}")
    return path


def ensure_realpath_confined(path: Path) -> Path:
    """Post-creation containment: resolve symlinks and re-verify the prefix.

    Called after mkdir / after any write, so a symlink planted inside a
    workspace can't redirect reads/writes elsewhere on the host.
    """
    root = str(SANDBOX_ROOT.resolve()) + os.sep
    real = Path(os.path.realpath(path))
    if not str(real).startswith(root):
        raise ValueError(f"symlink escape detected: {path} -> {real}")
    return real


# --------------------------------------------------------------------------- #
# Lifecycle
# --------------------------------------------------------------------------- #

_active: dict[str, dict[str, Any]] = {}  # task_id -> {container, user_id, workspace}


def _user_network_name(user_id: str) -> str:
    return f"agent_net_{validate_id(user_id, 'user')}"


def _ensure_user_network(user_id: str):
    client = _client()
    name = _user_network_name(user_id)
    try:
        return client.networks.get(name)
    except Exception:
        logger.info("creating user network", extra={"user_id": user_id})
        return client.networks.create(name, driver="bridge", labels={"tenant": user_id})


async def start_task_sandbox(user_id: str, task_id: str) -> Path:
    """One long-lived container per task, on the user's own network."""
    workspace = workspace_path(user_id, task_id)
    workspace.mkdir(parents=True, exist_ok=True)
    ensure_realpath_confined(workspace)

    def _create():
        network = _ensure_user_network(user_id)
        existing = None
        try:
            existing = _client().containers.get(f"sbx_{task_id}")
        except Exception:
            pass
        if existing is not None:
            existing.remove(force=True)
        container = _client().containers.run(
            _IMAGE,
            name=f"sbx_{task_id}",
            detach=True,
            network=network.name,
            mem_limit=f"{settings.sandbox.memory_mb}m",
            cpu_quota=int(settings.sandbox.cpu_quota * 100_000),
            cpu_period=100_000,
            pids_limit=settings.sandbox.pids_limit,
            volumes={str(workspace): {"bind": "/workspace", "mode": "rw"}},
            working_dir="/workspace",
            environment={},          # no env vars, ever
            labels={"tenant": user_id, "task": task_id},
        )
        return container

    container = await asyncio.to_thread(_create)
    _active[task_id] = {"container": container, "user_id": user_id, "workspace": workspace}
    logger.info("sandbox started", extra={"user_id": user_id, "task_id": task_id})
    return workspace


async def stop_task_sandbox(task_id: str) -> None:
    entry = _active.pop(task_id, None)
    if entry is None:
        return

    def _destroy():
        try:
            entry["container"].remove(force=True)
        except Exception:
            logger.exception("sandbox destroy failed", extra={"task_id": task_id})

    await asyncio.to_thread(_destroy)
    logger.info("sandbox stopped", extra={"task_id": task_id})


def _get_container(task_id: str):
    entry = _active.get(task_id)
    if entry is None:
        raise SandboxUnavailable("no sandbox for this task (was it started?)")
    return entry


async def _exec(task_id: str, cmd: list[str], timeout: float | None = None) -> tuple[int, bytes, bytes]:
    entry = _get_container(task_id)

    def _run():
        return entry["container"].exec_run(cmd, demux=True, workdir="/workspace")

    timeout = timeout or settings.limits.task_timeout_seconds
    code, output = await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout)
    stdout = (output[0] or b"") if isinstance(output, tuple) else (output or b"")
    stderr = (output[1] or b"") if isinstance(output, tuple) else b""
    return code, stdout, stderr


async def run_files(
    task_id: str,
    files: dict[str, str],
    entry: str,
    argv: list[str] | None = None,
    timeout: float | None = None,
) -> tuple[int, str, str]:
    """Write ``files`` into the task workspace (confined) and run
    ``python3 <entry> <argv...>`` inside the ALREADY-RUNNING task sandbox.

    Service-level helper for watcher checks and skill entrypoints — the
    model never calls this directly; it goes through the tools. Tenancy:
    the workspace/container is derived from (user_id, task_id) exactly as
    for model-driven runs, and every written path is containment-checked.
    Returns (exit_code, stdout, stderr) as text.
    """
    entry = entry.strip().lstrip("/")
    if not entry or ".." in Path(entry).parts or Path(entry).is_absolute():
        raise ValueError(f"unsafe entry path: {entry!r}")
    for rel in files:
        if rel.startswith("/") or ".." in Path(rel).parts:
            raise ValueError(f"unsafe file path: {rel!r}")
    for rel, content in files.items():
        target = _confined_read_path(task_id, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        ensure_realpath_confined(target)
    code, out, err = await _exec(
        task_id, ["python3", f"/workspace/{entry}", *(argv or [])], timeout=timeout
    )
    return (
        code,
        out.decode(errors="replace") if out else "",
        err.decode(errors="replace") if err else "",
    )


# --------------------------------------------------------------------------- #
# Tools (all confined to the acting user's workspace)
# --------------------------------------------------------------------------- #


def _task_ids() -> tuple[str, str]:
    from tools.base import current_task_id, current_user_id

    return current_user_id.get() or "", current_task_id.get() or ""


def _confined_read_path(task_id: str, rel_path: str) -> Path:
    entry = _get_container(task_id)
    workspace: Path = entry["workspace"]
    if rel_path.startswith("/") or ".." in Path(rel_path).parts:
        raise ValueError("path must be relative to the task workspace")
    target = (workspace / rel_path).resolve()
    if not str(target).startswith(str(workspace) + os.sep):
        raise ValueError("path escapes the task workspace")
    return ensure_realpath_confined(target)


@tool(
    "run_code",
    "Run a short program in your own sandbox and get stdout/stderr/exit code. "
    "Use for calculations, data parsing, file processing.",
    risk="safe",
)
async def run_code(language: str, code: str) -> dict:
    """Execute code inside this task's container (resource-capped)."""
    uid, tid = _task_ids()
    if language not in _LANGS:
        return ToolResult(ok=False, error=f"unsupported language {language!r}; supported: {sorted(_LANGS)}")
    if len(code) > 100_000:
        return ToolResult(ok=False, error="code too long (max 100k chars)")
    if not _active.get(tid):
        await start_task_sandbox(uid, tid)

    interpreter, ext = _LANGS[language]
    script = f"task_script{ext}"
    target = _confined_read_path(tid, script)
    target.write_text(code)
    ensure_realpath_confined(target)

    code_, out, err = await _exec(tid, [interpreter, f"/workspace/{script}"], timeout=120)
    return {
        "exit_code": code_,
        "stdout": out.decode(errors="replace")[:TRUNC],
        "stderr": err.decode(errors="replace")[:TRUNC],
    }


TRUNC = 15_000


@tool(
    "install_package",
    "Install a Python package into your sandbox with pip (e.g. 'yfinance').",
    risk="moderate",
)
async def install_package(name: str) -> dict:
    """pip install inside the user's own container."""
    uid, tid = _task_ids()
    if not re.match(r"^[A-Za-z0-9_.=<>~,+-]{1,100}$", name.strip()):
        return ToolResult(ok=False, error=f"not a valid package spec: {name!r}")
    if not _active.get(tid):
        await start_task_sandbox(uid, tid)
    code_, out, err = await _exec(tid, ["pip", "install", "--user", name.strip()], timeout=300)
    return {
        "exit_code": code_,
        "output": ((out or b"") + (err or b"")).decode(errors="replace")[:TRUNC],
    }


@tool("read_file", "Read a file from this task's workspace.", risk="safe")
async def read_file(path: str) -> str:
    target = _confined_read_path(_task_ids()[1], path)
    data = target.read_bytes()
    return data.decode(errors="replace")[:TRUNC]


@tool("write_file", "Write a file into this task's workspace.", risk="safe")
async def write_file(path: str, content: str) -> dict:
    uid, tid = _task_ids()
    if not _active.get(tid):
        await start_task_sandbox(uid, tid)
    target = _confined_read_path(tid, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    ensure_realpath_confined(target)
    return {"written": path, "bytes": len(content.encode())}


# --------------------------------------------------------------------------- #
# Retention sweep (called from main.py; Phase 3 folds this into the scheduler)
# --------------------------------------------------------------------------- #


async def purge_expired_workspaces() -> int:
    """Remove workspaces older than the retention window. Tenant-safe: only
    ever walks inside SANDBOX_ROOT."""
    cutoff_hours = settings.sandbox.workspace_retention_hours

    def _purge() -> int:
        removed = 0
        root = SANDBOX_ROOT
        if not root.exists():
            return 0
        now = time.time()
        for user_dir in root.iterdir():
            for task_dir in user_dir.iterdir():
                try:
                    if now - task_dir.stat().st_mtime > cutoff_hours * 3600:
                        import shutil

                        shutil.rmtree(task_dir, ignore_errors=True)
                        removed += 1
                except FileNotFoundError:
                    continue
            try:
                user_dir.rmdir()  # remove empty user dirs
            except OSError:
                pass
        return removed

    return await asyncio.to_thread(_purge)
