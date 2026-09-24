"""tools.base: schema generation, error capture, tenancy context, wrapper."""

from __future__ import annotations

import pytest

from tools import base as tb
from tools.base import call_tool, registry, tool


@tool("p2_echo", "echo its input", risk="safe")
async def p2_echo(text: str, times: int = 1) -> str:
    return text * times


@tool("p2_boom", "always raises", risk="safe")
async def p2_boom(why: str) -> str:
    raise RuntimeError(f"exploded: {why}")


@tool("p2_moderate", "moderate risk no-op", risk="moderate")
async def p2_moderate(action: str) -> str:
    return f"did {action}"


@tool("p2_external", "returns external content", risk="safe")
async def p2_external(page: str) -> tb.ExternalContent:
    return tb.ExternalContent(text=f"content of {page}", source="https://example.com")


@tool("p2_sneaky", "model tries to pass user_id", risk="safe")
async def p2_sneaky(text: str) -> str:
    return f"ran for context user: {text}"


def test_schema_generated_from_type_hints():
    spec = registry.get("p2_echo")
    assert spec is not None
    schema = spec.params_schema
    assert schema["properties"]["text"]["type"] == "string"
    assert schema["properties"]["times"]["type"] == "integer"
    assert schema["required"] == ["text"]
    # exported list carries the schema too
    exported = {t["name"]: t for t in registry.export_for_anthropic("free", "user")}
    assert "p2_echo" in exported and "input_schema" in exported["p2_echo"]


def test_untyped_param_rejected():
    with pytest.raises(tb.ToolError, match="type hint"):
        @tool("p2_untyped", "no hints", risk="safe")
        async def p2_untyped(x) -> str:  # noqa: ANN001
            return x


def test_duplicate_name_rejected():
    with pytest.raises(tb.ToolError, match="duplicate"):
        @tool("p2_echo", "another one", risk="safe")
        async def p2_echo_again(text: str) -> str:
            return text


async def test_refuses_without_task_context():
    result = await call_tool("p2_echo", {"text": "hi"})
    assert result.ok is False
    assert "no task context" in result.error


async def test_error_captured_not_raised():
    with tb_current("u1", "t1"):
        result = await call_tool("p2_boom", {"why": "because"})
    assert result.ok is False
    assert "exploded: because" in result.error


async def test_model_supplied_user_id_stripped():
    with tb_current("u1", "t1"):
        result = await call_tool("p2_sneaky", {"text": "x", "user_id": "u-victim"})
    assert result.ok is True  # the call still runs — for its own user's context
    # and the log recorded the strip (checked via caplog in test_logs context tests)


async def test_external_content_wrapped_and_source_typed():
    with tb_current("u1", "t1"):
        result = await call_tool("p2_external", {"page": "docs"})
    assert result.ok
    assert result.data.startswith('<untrusted_content source="https://example.com">')
    assert "content of docs" in result.data
    assert result.data.endswith("</untrusted_content>")


async def test_unknown_tool_clean_error():
    result = await call_tool("no_such_tool", {})
    assert result.ok is False and "unknown tool" in result.error


class tb_current:
    """Sync CM helper mirroring tests.p2_conftest.task_context."""

    def __init__(self, user_id: str, task_id: str = "t1", source: str = "user"):
        self.ctx = (user_id, task_id, source)

    def __enter__(self):
        import contextvars

        self._u = tb.current_user_id.set(self.ctx[0])
        self._t = tb.current_task_id.set(self.ctx[1])
        self._s = tb.current_task_source.set(self.ctx[2])
        self._cv = contextvars
        return self

    def __exit__(self, *exc):
        self._cv  # noqa: B018
        tb.current_user_id.reset(self._u)
        tb.current_task_id.reset(self._t)
        tb.current_task_source.reset(self._s)
        return False
