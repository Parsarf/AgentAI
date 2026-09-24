"""Config loading: typed merge, loud failures, masked secrets."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from core.config import CONFIG_DIR, ConfigError, load_settings

TEST_ENV = {
    "anthropic_api_key": "sk-test-secret-abcdef123456",
    "session_secret": "s" * 48,
    "database_url": "postgresql://agent:secretpw@localhost:5432/agent_test",
}


def test_loads_yaml_into_typed_settings():
    s = load_settings(config_dir=CONFIG_DIR, env=TEST_ENV, load_env_file=False)
    assert s.models.planner
    assert s.models.cheap
    assert s.limits.max_steps_job < s.limits.max_steps_interactive
    assert s.plans.tier("free").payments_enabled is False
    assert s.plans.tier("pro").payments_enabled is True
    assert isinstance(s.plans.tier("free").hard_cap_usd, Decimal)
    assert Decimal("10.00") == s.plans.tier("free").hard_cap_usd
    assert s.approval_rules.fallback == "require_approval"
    assert any(r.action == "deny" for r in s.approval_rules.rules)
    assert all(server.enabled is False for server in s.mcp_servers.servers)


def test_masked_output_leaks_no_secrets():
    s = load_settings(config_dir=CONFIG_DIR, env=TEST_ENV, load_env_file=False)
    masked = s.masked()
    flat = repr(masked)
    assert "sk-test-secret-abcdef123456" not in flat
    assert "secretpw" not in flat
    assert masked["anthropic_api_key"] == "[SET]"
    assert masked["database_url"].startswith("postgresql://agent:***@")
    assert masked["base_url"] == "http://localhost:8000"  # not a secret


def test_bad_yaml_names_the_file(tmp_path: Path):
    (tmp_path / "settings.yaml").write_text("models: [oops\n  bad:")
    for name in ("limits.yaml", "plans.yaml", "mcp_servers.yaml"):
        (tmp_path / name).write_text("{}")
    with pytest.raises(ConfigError) as excinfo:
        load_settings(config_dir=tmp_path, env=TEST_ENV, load_env_file=False)
    assert "settings.yaml" in str(excinfo.value)


def test_unknown_plan_tier_names_the_key():
    s = load_settings(config_dir=CONFIG_DIR, env=TEST_ENV, load_env_file=False)
    with pytest.raises(ConfigError) as excinfo:
        s.plans.tier("gold")
    assert "gold" in str(excinfo.value)
    assert "plans.yaml" in str(excinfo.value)


def test_require_missing_secret_names_part0a_fix():
    s = load_settings(config_dir=CONFIG_DIR, env={}, load_env_file=False)
    with pytest.raises(ConfigError) as excinfo:
        s.require("anthropic_api_key")
    assert "ANTHROPIC_API_KEY" in str(excinfo.value)
    assert "Part 0a" in str(excinfo.value)


def test_short_session_secret_rejected():
    with pytest.raises(ConfigError) as excinfo:
        load_settings(config_dir=CONFIG_DIR, env={"session_secret": "short"}, load_env_file=False)
    assert "SESSION_SECRET" in str(excinfo.value)
