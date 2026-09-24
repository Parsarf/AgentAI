"""Per-user skill library: folders the agent writes for itself.

Each skill lives UNDER THE OWNING USER'S PREFIX:
    skills/<user_id>/<skill_name>/
with a generated ``skill.yaml`` (name, description, args_schema, risk,
entrypoint) plus either ``run.py`` (executable code) or ``instructions.md``
(a playbook the agent follows inline). Stats (uses/successes/failures,
needs_review) live in the tenant-scoped ``skills_meta`` table.

Layout rules are identical to sandbox workspaces: ids/names validated, every
path confinement-asserted, so cross-user access is structurally impossible —
a user's skills are readable/writable ONLY under that user's prefix.

A shared/opt-in skill marketplace is a DELIBERATE NON-GOAL of this phase:
sharing, if ever built, would be an explicit user action, never automatic.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from core import db
from core.logging import get_logger
from tools import sandbox

logger = get_logger(__name__)

SKILLS_ROOT = Path(__file__).resolve().parent.parent / "skills"

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SKILL_RISKS = ("safe", "moderate")  # skills may NEVER declare high
_MAX_FILES = 20
_MAX_FILE_CHARS = 100_000
_MAX_SCHEMA_CHARS = 8_000


class SkillError(Exception):
    """A skill operation was refused (message is actionable, existence-safe)."""


# --------------------------------------------------------------------------- #
# Path helpers — the ONLY ways a skills path is ever constructed
# --------------------------------------------------------------------------- #


def _validated_user_id(user_id: str) -> str:
    return sandbox.validate_id(str(user_id), "user")


def _confined(root: Path, *parts: str) -> Path:
    """Join under root, resolve, and re-verify the prefix (kills traversal)."""
    root_real = Path(os.path.realpath(root))
    path = Path(os.path.realpath(root_real.joinpath(*parts)))
    if path != root_real and not str(path).startswith(str(root_real) + os.sep):
        raise SkillError("path escapes the skills root")
    return path


def validate_skill_name(name: str) -> str:
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise SkillError(
            "invalid skill name: use lowercase letters, digits, '-', '_' "
            "(max 64 chars, starting with a letter or digit)"
        )
    return name


def skill_dir(user_id: str, name: str) -> Path:
    """skills/<user_id>/<skill_name>/ — cross-user access structurally impossible."""
    return _confined(SKILLS_ROOT, _validated_user_id(user_id), validate_skill_name(name))


def checks_dir(user_id: str) -> Path:
    return _confined(SKILLS_ROOT, _validated_user_id(user_id), "_checks")


def check_script_path(user_id: str, job_id: str) -> Path:
    return _confined(checks_dir(user_id), f"{sandbox.validate_id(job_id, 'job')}.py")


# --------------------------------------------------------------------------- #
# Watcher check scripts (written at job creation; run by the scheduler service)
# --------------------------------------------------------------------------- #


def write_check_script(user_id: str, job_id: str, source: str) -> Path:
    """Save a watcher's check script under the user's own _checks/ prefix."""
    if not source or not source.strip():
        raise SkillError("check script is empty")
    try:
        compile(source, "check_script.py", "exec")
    except SyntaxError as exc:
        raise SkillError(f"check script does not compile: {exc}") from exc
    path = check_script_path(user_id, job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    return path


def read_check_script(user_id: str, job_id: str) -> str:
    path = check_script_path(user_id, job_id)
    try:
        return path.read_text()
    except FileNotFoundError as exc:
        raise SkillError(f"check script missing at {path.name}") from exc


def delete_check_script(user_id: str, job_id: str) -> None:
    """Best-effort removal of the user's own check script (job deletion)."""
    with contextlib.suppress(OSError, SkillError):
        check_script_path(user_id, job_id).unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# save / load / list
# --------------------------------------------------------------------------- #


def _validate_files(files: dict[str, str]) -> dict[str, str]:
    if not isinstance(files, dict) or not files:
        raise SkillError("files must be a non-empty object of {path: content}")
    if len(files) > _MAX_FILES:
        raise SkillError(f"too many files (max {_MAX_FILES})")
    clean: dict[str, str] = {}
    for rel, content in files.items():
        rel = str(rel)
        if rel.startswith("/") or Path(rel).is_absolute() or ".." in Path(rel).parts:
            raise SkillError(f"unsafe file path: {rel!r}")
        if not rel or len(rel) > 200:
            raise SkillError(f"unsafe file path: {rel!r}")
        if not isinstance(content, str) or len(content) > _MAX_FILE_CHARS:
            raise SkillError(f"file {rel!r}: missing or too large (max {_MAX_FILE_CHARS} chars)")
        clean[rel] = content
    has_code = "run.py" in clean
    has_playbook = "instructions.md" in clean
    if not has_code and not has_playbook:
        raise SkillError("a skill needs either run.py (code) or instructions.md (playbook)")
    if has_code:
        try:
            compile(clean["run.py"], "run.py", "exec")
        except SyntaxError as exc:
            raise SkillError(f"run.py does not compile: {exc}") from exc
    if has_playbook and not clean["instructions.md"].strip():
        raise SkillError("instructions.md is empty")
    return clean


def _validate_args_schema(args_schema: Any) -> dict:
    if not isinstance(args_schema, dict):
        raise SkillError("args_schema must be a JSON-schema object (e.g. {'type': 'object', ...})")
    try:
        encoded = json.dumps(args_schema)
    except (TypeError, ValueError) as exc:
        raise SkillError(f"args_schema is not JSON-serializable: {exc}") from exc
    if len(encoded) > _MAX_SCHEMA_CHARS:
        raise SkillError("args_schema too large")
    if "type" in args_schema and args_schema["type"] != "object":
        raise SkillError("args_schema type must be 'object'")
    return args_schema


async def save_skill(
    user_id: str,
    name: str,
    description: str,
    args_schema: dict,
    risk: str,
    files: dict[str, str],
) -> dict:
    """Validate + write the skill folder under the user's prefix, upsert meta.

    Re-saving an existing skill replaces its files and clears needs_review.
    """
    validate_skill_name(name)
    if risk not in _SKILL_RISKS:
        raise SkillError(f"skill risk must be one of {_SKILL_RISKS} — skills may never declare 'high'")
    description = str(description or "").strip()
    if not description:
        raise SkillError("description is required")
    if len(description) > 2000:
        raise SkillError("description too long (max 2000 chars)")
    schema = _validate_args_schema(args_schema)
    clean = _validate_files(files)

    kind = "code" if "run.py" in clean else "playbook"
    entrypoint = "run.py" if kind == "code" else "instructions.md"
    folder = skill_dir(user_id, name)
    folder.mkdir(parents=True, exist_ok=True)

    meta_yaml = {
        "name": name,
        "description": description,
        "args_schema": schema,
        "risk": risk,
        "entrypoint": entrypoint,
        "kind": kind,
    }
    (folder / "skill.yaml").write_text(yaml.safe_dump(meta_yaml, sort_keys=False))
    for rel, content in clean.items():
        target = _confined(folder, rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)

    await db.save_skill_meta(_uuid(user_id), name)
    logger.info(
        "skill saved",
        extra={"user_id": str(user_id), "skill": name, "kind": kind, "risk": risk},
    )
    return {"name": name, "kind": kind, "risk": risk, "entrypoint": entrypoint}


def _uuid(value: str):
    from uuid import UUID

    return UUID(str(value))


async def load_skill(user_id: str, name: str) -> dict | None:
    """The user's OWN skill (meta + yaml + files), or None.

    None is returned whether the skill doesn't exist OR belongs to someone
    else — a name outside this user's prefix is simply not found.
    """
    try:
        folder = skill_dir(user_id, name)
    except SkillError:
        return None
    yaml_path = folder / "skill.yaml"
    meta = await db.get_skill_meta(_uuid(user_id), validate_skill_name(name))
    if meta is None or not yaml_path.is_file():
        return None
    try:
        parsed = yaml.safe_load(yaml_path.read_text()) or {}
    except yaml.YAMLError:
        logger.warning("skill.yaml unparsable", extra={"user_id": str(user_id), "skill": name})
        return None
    files = {
        str(p.relative_to(folder)): p.read_text(errors="replace")
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name != "skill.yaml"
    }
    return {"meta": meta, "spec": parsed, "files": files, "dir": folder}


async def list_skills(user_id: str) -> list[dict]:
    """The user's own skills with stats; needs_review is surfaced, never
    auto-deleted."""
    out = []
    for meta in await db.list_skill_meta(_uuid(user_id)):
        try:
            spec_dir = skill_dir(user_id, meta.name)
            parsed = yaml.safe_load((spec_dir / "skill.yaml").read_text()) or {}
        except (SkillError, OSError, yaml.YAMLError):
            parsed = {}
        out.append(
            {
                "name": meta.name,
                "description": parsed.get("description", ""),
                "kind": parsed.get("kind", ""),
                "risk": parsed.get("risk", ""),
                "uses": meta.uses,
                "successes": meta.successes,
                "failures": meta.failures,
                "needs_review": not meta.reviewed,
                "last_used_at": meta.last_used_at.isoformat() if meta.last_used_at else None,
            }
        )
    return out


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #


async def run_skill(user_id: str, skill_name: str, args: dict | None, task_id: str) -> dict:
    """Execute the user's OWN skill inside THEIR OWN task sandbox.

    Code skills: the skill folder is materialized inside the task workspace
    (which is derived from this user's id — the executing container is the
    runner's own) and run.py is invoked with the args as one JSON argv.
    Playbook skills: the instructions are returned for the orchestrator/model
    to follow inline. Outcomes are recorded; enough failures flips the
    needs_review flag (never deletes).
    """
    loaded = await load_skill(user_id, skill_name)
    if loaded is None:
        # Existence-safe: same message whether missing or another user's.
        raise SkillError("skill not found")
    spec: dict = loaded["spec"] or {}

    if spec.get("kind") == "playbook" or spec.get("entrypoint") == "instructions.md":
        text = loaded["files"].get("instructions.md", "")
        await db.record_skill_use(_uuid(user_id), skill_name, ok=True)
        return {"kind": "playbook", "name": skill_name, "instructions": text}

    namespaced = {f"skill/{skill_name}/{rel}": content for rel, content in loaded["files"].items()}
    if "skill/" + skill_name + "/run.py" not in namespaced:
        await db.record_skill_use(_uuid(user_id), skill_name, ok=False)
        raise SkillError("code skill has no run.py entrypoint")
    payload = json.dumps(args or {})
    try:
        code, out, err = await sandbox.run_files(
            task_id,
            namespaced,
            entry=f"skill/{skill_name}/run.py",
            argv=[payload],
            timeout=120.0,
        )
    except sandbox.SandboxUnavailable as exc:
        await db.record_skill_use(_uuid(user_id), skill_name, ok=False)
        raise SkillError(str(exc)) from exc
    except Exception as exc:
        await db.record_skill_use(_uuid(user_id), skill_name, ok=False)
        raise SkillError(f"skill execution failed: {exc}") from exc

    ok = code == 0
    await db.record_skill_use(_uuid(user_id), skill_name, ok=ok)
    return {"kind": "code", "name": skill_name, "exit_code": code, "stdout": out, "stderr": err}
