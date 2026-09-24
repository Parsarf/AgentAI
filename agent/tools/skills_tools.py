"""Model-facing surface over the per-user skill library.

The acting user comes from task context only; every operation is scoped to
their own prefix. ``run_skill``'s approval gate reads THE SKILL'S DECLARED
risk (safe|moderate — skills can never declare high) via a risk resolver;
if the skill can't be resolved, the tool's declared 'moderate' applies
(fail closed).
"""

from __future__ import annotations

from typing import Any, Literal

from core import skills
from core.logging import get_logger
from tools.base import (
    Risk,
    ToolResult,
    current_task_id,
    current_user_id,
    tool,
)

logger = get_logger(__name__)


@tool(
    "save_skill",
    "Save a reusable skill for THIS user: a folder with run.py (code, gets "
    "args as one JSON argv, prints results) or instructions.md (a playbook "
    "you follow when the skill is invoked), plus name/description/args_schema/"
    "risk. Prefer turning repeated successful patterns into skills.",
    risk="moderate",
)
async def save_skill(
    name: str,
    description: str,
    args_schema: dict,
    risk: Literal["safe", "moderate"] = "safe",
    files: dict[str, str] | None = None,
) -> ToolResult:
    """Save into the acting user's own library."""
    uid = current_user_id.get()
    if not isinstance(files, dict) or not files:
        return ToolResult(ok=False, error="files must be an object of {path: content}")
    try:
        saved = await skills.save_skill(
            str(uid), name, description, args_schema, str(risk), files
        )
    except skills.SkillError as exc:
        return ToolResult(ok=False, error=str(exc))
    return ToolResult(ok=True, data=saved)


@tool(
    "list_skills",
    "List this user's saved skills with usage stats and needs_review flags.",
    risk="safe",
)
async def list_skills() -> list[dict]:
    """Only the acting user's skills — the library has no shared space."""
    uid = current_user_id.get()
    return await skills.list_skills(str(uid))


async def _run_skill_risk(args: dict[str, Any]) -> Risk:
    """Per-call risk = the skill's declared risk, resolved from the ACTING
    user's own library. Unresolvable ⇒ 'moderate' (fail closed)."""
    uid = current_user_id.get()
    loaded = await skills.load_skill(str(uid), str(args.get("skill_name", "")))
    if loaded is None:
        return "moderate"
    risk = (loaded["spec"] or {}).get("risk", "moderate")
    return risk if risk in ("safe", "moderate") else "moderate"


@tool(
    "run_skill",
    "Run one of this user's saved skills by name. Code skills execute in the "
    "task sandbox with args; playbook skills return the instructions to follow.",
    risk="moderate",
    risk_resolver=_run_skill_risk,
)
async def run_skill(skill_name: str, args: dict | None = None) -> ToolResult:
    """Execute from the acting user's own library, in their own sandbox."""
    uid = current_user_id.get()
    tid = current_task_id.get()
    if not tid:
        return ToolResult(ok=False, error="internal: no task context for skill execution")
    try:
        result = await skills.run_skill(str(uid), skill_name, args, str(tid))
    except skills.SkillError as exc:
        return ToolResult(ok=False, error=str(exc))
    if result.get("kind") == "playbook":
        # External-ish content: it is stored text the model should treat as a
        # playbook, and it came from the user's own saved skill.
        from tools.base import ExternalContent

        return ToolResult(
            ok=True,
            data=ExternalContent(
                result["instructions"], source=f"skill:{result['name']} instructions.md"
            ),
        )
    return ToolResult(ok=True, data=result)
