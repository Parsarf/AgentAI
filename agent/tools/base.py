"""The tool system — the plug-in mechanism that makes the agent extensible.

Tenancy is structural:
- The acting ``user_id`` / ``task_id`` / ``task_source`` arrive via context
  variables set ONLY by the orchestrator. Tools never receive them from the
  model; a model-supplied ``user_id`` argument is stripped and logged.
- Every call passes through :func:`call_tool`, which refuses to run without
  task context, gates non-safe tools through ``core.approvals``, captures all
  exceptions into ``ToolResult(ok=False)``, truncates oversized outputs and
  wraps external content in ``<untrusted_content>`` tags.
"""

from __future__ import annotations

import asyncio
import contextvars
import inspect
import re
import time
import typing
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from core import approvals as approvals_mod
from core.logging import get_logger

logger = get_logger(__name__)

Risk = Literal["safe", "moderate", "high"]

current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user_id", default=None)
current_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_task_id", default=None)
current_task_source: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_task_source", default=None
)


def set_task_context_tokens(user_id: str, task_id: str) -> tuple[Any, Any]:
    """(user_id, task_id)-ordered setter the orchestrator/tests use.

    Returns tokens for :func:`reset_task_context`."""
    u = current_user_id.set(str(user_id))
    t = current_task_id.set(str(task_id))
    return (u, t)


def reset_task_context(tokens: tuple[Any, Any]) -> None:
    current_user_id.reset(tokens[0])
    current_task_id.reset(tokens[1])


#: Set by the orchestrator when approvals were already enforced in the agent
#: loop's permission hook, so the wrapper doesn't gate the same call twice.
approvals_prechecked: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "approvals_prechecked", default=False
)

TRUNCATE_AT = 20_000
_MAX_SCHEMA_DEPTH = 6


class ToolResult(BaseModel):
    ok: bool
    data: Any = None
    error: str | None = None


class ExternalContent:
    """Marker for content fetched from the outside world — the wrapper tags it."""

    def __init__(self, text: str, source: str) -> None:
        self.text = text
        self.source = source


@dataclass
class ToolSpec:
    name: str
    description: str
    risk: Risk
    handler: Callable[..., Awaitable[Any]]
    params_schema: dict[str, Any] = field(default_factory=dict)
    # Optional per-call risk resolution (e.g. run_skill inherits the saved
    # skill's declared risk). Receives the call args, resolves from the
    # ACTING USER's own data only. Failure ⇒ the declared risk (fail closed).
    risk_resolver: Callable[[dict[str, Any]], Awaitable[Risk]] | None = None


class ToolError(Exception):
    """A tool refused to run (not the model's fault; message is actionable)."""


# --------------------------------------------------------------------------- #
# JSON schema from type hints
# --------------------------------------------------------------------------- #

_PY_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _schema_for_annotation(annotation: Any, depth: int = 0) -> dict[str, Any]:
    if depth > _MAX_SCHEMA_DEPTH:
        return {}
    origin = typing.get_origin(annotation)
    if annotation is type(None):
        return {"type": "null"}
    if origin is typing.Literal:
        values = list(typing.get_args(annotation))
        base = _schema_for_annotation(type(values[0]), depth + 1)
        base["enum"] = [v for v in values if isinstance(v, (str, int, float, bool))]
        return base
    if origin in (list, list):
        (item,) = typing.get_args(annotation) or (Any,)
        return {"type": "array", "items": _schema_for_annotation(item, depth + 1)}
    if origin in (dict, dict):
        return {"type": "object"}
    if origin is typing.Union or str(origin) == "<class 'types.UnionType'>":
        members = [a for a in typing.get_args(annotation) if a is not type(None)]
        subs = [_schema_for_annotation(m, depth + 1) for m in members]
        non_null = [s for s in subs if s.get("type") != "null"]
        if len(non_null) == 1 and len(subs) != len(non_null):
            return non_null[0]  # Optional[T] → T
        return {"anyOf": subs}
    if annotation in _PY_TO_JSON:
        return {"type": _PY_TO_JSON[annotation]}
    if annotation is Any or annotation is inspect.Parameter.empty:
        return {}  # unknown → permissive
    return {}  # arbitrary classes: permissive; tools should use primitives


def build_params_schema(func: Callable) -> dict[str, Any]:
    """JSON schema from the handler's type hints. Untyped params are refused.

    Resolves PEP 563 string annotations via get_type_hints (the package uses
    `from __future__ import annotations` everywhere).
    """
    signature = inspect.signature(func)
    try:
        hints = typing.get_type_hints(func)
    except Exception as exc:
        raise ToolError(f"tool '{func.__name__}': cannot resolve type hints ({exc})") from exc
    properties: dict[str, Any] = {}
    required: list[str] = []
    for name, param in signature.parameters.items():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        if name not in hints:
            raise ToolError(f"tool '{func.__name__}': parameter '{name}' needs a type hint")
        schema = _schema_for_annotation(hints[name])
        properties[name] = schema or {"type": "string"}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": properties, "required": required}


# --------------------------------------------------------------------------- #
# Registry + decorator
# --------------------------------------------------------------------------- #


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ToolError(f"duplicate tool name: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def all(self) -> dict[str, ToolSpec]:
        return dict(self._tools)

    def export_for_sdk(self, plan_tier: str, task_source: str) -> list[dict[str, Any]]:
        """Tool list for the agent loop.

        Plan floor: capabilities a tier lacks are not even offered.
        Job-mode narrowing: high-risk tools are not offered to autonomous tasks.
        """
        from core.config import settings

        plan = settings.plan_for(plan_tier)
        exported = []
        for spec in self._tools.values():
            if spec.name in approvals_mod.BROWSER_TOOLS and not plan.browser_tools:
                continue
            if spec.name in approvals_mod.PAYMENT_TOOLS and (
                not plan.payments_enabled or not settings.payments.enabled
            ):
                continue
            if task_source == "job" and spec.risk == "high":
                continue
            exported.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "risk": spec.risk,
                    "input_schema": spec.params_schema,
                }
            )
        return exported

    def export_for_anthropic(self, plan_tier: str, task_source: str) -> list[dict[str, Any]]:
        """Anthropic messages-API tool format (direct-loop fallback)."""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["input_schema"],
            }
            for t in self.export_for_sdk(plan_tier, task_source)
        ]


registry = ToolRegistry()


def tool(
    name: str,
    description: str | None = None,
    risk: Risk = "safe",
    risk_resolver: Callable[[dict[str, Any]], Awaitable[Risk]] | None = None,
) -> Callable:
    """Register an async function as an agent tool.

    The handler returns plain data, a ToolResult, or ExternalContent. It must
    NOT take a user_id argument — tenancy comes from task context only.
    ``risk_resolver`` may compute a stricter/looser per-call risk from the
    acting user's own data; the wrapper gates on the resolved risk.
    """

    def decorator(func: Callable) -> Callable:
        doc = inspect.getdoc(func) or ""
        spec = ToolSpec(
            name=name,
            description=description or doc.splitlines()[0] if doc else name,
            risk=risk,
            handler=func,
            params_schema=build_params_schema(func),
            risk_resolver=risk_resolver,
        )
        registry.register(spec)
        func._tool_spec = spec  # type: ignore[attr-defined]
        return func

    return decorator


def auto_discover() -> int:
    """Import every module in the tools package so decorators run."""
    import importlib
    import pkgutil

    from . import __path__ as tool_paths

    count_before = len(registry.all())
    for module_info in pkgutil.iter_modules(tool_paths):
        if module_info.name in ("base",):
            continue
        importlib.import_module(f"tools.{module_info.name}")
    return len(registry.all()) - count_before


# --------------------------------------------------------------------------- #
# The enforcement wrapper — every tool call funnels through here
# --------------------------------------------------------------------------- #

_FORBIDDEN_MODEL_ARGS = ("user_id", "task_id", "task_source")


async def call_tool(name: str, args: dict[str, Any] | None = None) -> ToolResult:
    spec = registry.get(name)
    if spec is None:
        return ToolResult(ok=False, error=f"unknown tool: {name}")

    user_id = current_user_id.get()
    task_id = current_task_id.get()
    task_source = current_task_source.get()
    if not user_id or not task_id:
        return ToolResult(
            ok=False,
            error="internal: no task context — tools can only run inside a task",
        )

    args = dict(args or {})
    injected = [k for k in _FORBIDDEN_MODEL_ARGS if k in args]
    if injected:
        logger.warning(
            "model tried to supply protected args — stripped",
            extra={"tool": name, "stripped_args": injected},
        )
        for k in injected:
            args.pop(k)

    risk = await _effective_risk(spec, args)
    logger.info(
        "tool.call.start",
        extra={"tool": name, "risk": risk, "tool_args": _safe_args(name, args)},
    )
    started = time.monotonic()

    # Payment tools own their gating in core.purchases (one validation +
    # approval path). The generic gate below must never run for them: the
    # preflight denies BEFORE any approval row exists, and the task-wide
    # approvals_prechecked flag is never treated as purchase permission —
    # permission binds to the purchase row and its single owner approval.
    if name in approvals_mod.PAYMENT_TOOLS or name == "check_spend_status":
        try:
            result = await spec.handler(**args)
            if not isinstance(result, ToolResult):
                result = ToolResult(ok=True, data=result)
            return _finish(spec, args, started, result, user_id, task_id)
        except asyncio.CancelledError:
            raise
        except TypeError as exc:
            return _finish(
                spec,
                args,
                started,
                ToolResult(ok=False, error=f"bad arguments for {name}: {exc}"),
                user_id,
                task_id,
            )
        except Exception:
            logger.exception("payment dispatch failed", extra={"tool": name})
            return _finish(
                spec, args, started, ToolResult(ok=False, error="purchase preflight failed"), user_id, task_id
            )

    # ---- approval gate (skipped only when the loop's permission hook already ran it)
    if risk != "safe" and not approvals_prechecked.get():
        decision = await approvals_mod.check(
            user_id=user_id,
            tool_name=name,
            tool_args=args,
            risk=risk,
            task_source=task_source or "user",
        )
        if decision.action == "deny":
            return _finish(
                spec,
                args,
                started,
                ToolResult(ok=False, error=f"denied by your approval settings: {decision.reason}"),
                user_id,
                task_id,
            )
        if decision.action == "require_approval":
            approved = await approvals_mod.request_and_wait(
                user_id=user_id,
                task_id=task_id,
                action_summary=f"{name}: {approvals_mod.summarize(args)}",
                details_json={"tool": name, "args": _safe_args(name, args), "risk": spec.risk},
            )
            if not approved:
                return _finish(
                    spec,
                    args,
                    started,
                    ToolResult(ok=False, error="denied: the user did not approve this action"),
                    user_id,
                    task_id,
                )

    # ---- execute, never raise to the agent
    try:
        result = await spec.handler(**args)
        if isinstance(result, ToolResult):
            tool_result = result
        else:
            tool_result = ToolResult(ok=True, data=result)
    except asyncio.CancelledError:
        raise
    except TypeError as exc:
        tool_result = ToolResult(ok=False, error=f"bad arguments for {name}: {exc}")
    except Exception as exc:
        logger.exception("tool raised", extra={"tool": name})
        tool_result = ToolResult(ok=False, error=f"{name} failed: {exc}")

    # ---- external content tagging + truncation
    if tool_result.ok and isinstance(tool_result.data, ExternalContent):
        inner = tool_result.data.text
        if len(inner) > TRUNCATE_AT:
            inner = inner[:TRUNCATE_AT] + "\n[truncated]"
        tool_result.data = (
            f'<untrusted_content source="{_esc(tool_result.data.source)}">\n{inner}\n</untrusted_content>'
        )
    elif tool_result.ok and isinstance(tool_result.data, str) and len(tool_result.data) > TRUNCATE_AT:
        tool_result.data = tool_result.data[:TRUNCATE_AT] + "\n[truncated]"

    return _finish(spec, args, started, tool_result, user_id, task_id)


def _esc(text: str) -> str:
    return re.sub(r"[<>&\"]", "", str(text))[:120]


async def _effective_risk(spec: ToolSpec, args: dict[str, Any]) -> Risk:
    """Per-call risk: the resolver's verdict, or the declared risk on any
    resolver failure (fail closed)."""
    if spec.risk_resolver is None:
        return spec.risk
    try:
        return await spec.risk_resolver(args)
    except Exception:
        logger.exception("risk resolver failed — using declared risk", extra={"tool": spec.name})
        return spec.risk


def _finish(
    spec: ToolSpec,
    args: dict[str, Any],
    started: float,
    result: ToolResult,
    user_id: str,
    task_id: str,
) -> ToolResult:
    logger.info(
        "tool.call.end",
        extra={
            "tool": spec.name,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "ok": result.ok,
            "error": result.error[:200] if result.error else None,
        },
    )
    return result


def _safe_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Args for logging — tools dealing in secrets register them with the
    redaction filter, but belt-and-braces: cap size here too."""
    capped = {k: (str(v)[:300]) for k, v in args.items()}
    return capped
