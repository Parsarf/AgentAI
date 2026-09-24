"""The single source of truth for configuration.

Loads operator secrets from ``.env`` (pydantic-settings) and merges the four
YAML files in ``config/`` into typed pydantic models. Validates at import so
a typo fails loudly with the file and key named. Exposes one global
``settings`` object plus ``reload()``.

Secrets never appear in reprs/logs: :meth:`Settings.masked` and the redaction
filter in core.logging see to that.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

import core.logging as clog

ROOT = Path(__file__).resolve().parent.parent  # the agent/ package root
CONFIG_DIR = ROOT / "config"
ENV_FILE = ROOT / ".env"


class ConfigError(Exception):
    """Configuration is missing or invalid. The message names the file/key."""


_SECRET_HINTS: dict[str, str] = {
    "anthropic_api_key": "ANTHROPIC_API_KEY — Part 0a item #1 (Anthropic API)",
    "search_api_key": "SEARCH_API_KEY — Part 0a item #7 (web search API)",
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN — Part 0a item #2 (@BotFather)",
    "database_url": "DATABASE_URL — Postgres 16 + pgvector (Part 0a item #3 hosting)",
    "email_api_key": "EMAIL_API_KEY — Part 0a item #5 (transactional email)",
    "stripe_secret_key": "STRIPE_SECRET_KEY — Part 0a item #9 (Stripe, Phase 5)",
    "stripe_webhook_secret": "STRIPE_WEBHOOK_SECRET — Part 0a item #9 (Stripe, Phase 5)",
    "vault_master_key": "VAULT_MASTER_KEY — Part 0a item #8 (KMS / generated key, Phase 4)",
    "session_secret": "SESSION_SECRET — generate: openssl rand -base64 48",
    "base_url": "BASE_URL — public URL of the web app (Part 0a item #3)",
}

_NON_SECRET_KEYS = frozenset({"base_url"})


# --------------------------------------------------------------------------- #
# Secrets (from .env / environment)
# --------------------------------------------------------------------------- #


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    anthropic_api_key: str | None = None
    search_api_key: str | None = None
    telegram_bot_token: str | None = None
    database_url: str = "postgresql://agent@localhost:5432/agent"
    email_api_key: str | None = None
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    vault_master_key: str | None = None
    session_secret: str | None = None
    base_url: str = "http://localhost:8000"


# --------------------------------------------------------------------------- #
# YAML-backed typed models
# --------------------------------------------------------------------------- #


class ModelsConfig(BaseModel):
    planner: str
    worker: str
    cheap: str


class ModelPrices(BaseModel):
    input_per_mtok_usd: Decimal
    output_per_mtok_usd: Decimal
    cache_write_per_mtok_usd: Decimal = Decimal("0")
    cache_read_per_mtok_usd: Decimal = Decimal("0")


class LimitsConfig(BaseModel):
    max_steps_interactive: int
    max_steps_job: int
    task_timeout_seconds: int
    context_token_budget: int
    approval_timeout_seconds: int


class SandboxConfig(BaseModel):
    cpu_quota: float
    memory_mb: int
    pids_limit: int
    network_enabled: bool
    workspace_retention_hours: int


class SchedulerConfig(BaseModel):
    # How often the scheduler service wakes to look for due jobs (seconds).
    tick_seconds: float
    # A job auto-pauses after this many consecutive failed runs.
    max_consecutive_failures: int


class QuietHours(BaseModel):
    start: str
    end: str


class BrowserConfig(BaseModel):
    # Playwright runs headless by default (cost + reliability); screenshots
    # are the fallback, text snapshots the main view.
    headless: bool
    # Dev/test mode: run a LOCAL chromium with per-user persistent profiles
    # instead of a per-user container reached over CDP. Never enable in
    # production — container mode is where the per-user network isolation
    # applies.
    local_mode: bool = False
    # Default navigation/action timeout for browser tools (ms).
    default_timeout_ms: int = 15000
    # Text snapshot size cap (chars) before truncation.
    snapshot_max_chars: int = 20000
    # Root directory for per-user persistent profiles. Defaults to the
    # /data volume convention; override for local dev.
    profile_root: str = "/data/browser_profiles"
    # A per-user profile dir older than this many days AND unused is purged
    # by the maintenance sweep (0 = never purge).
    profile_retention_days: int = 30


class VaultConfig(BaseModel):
    # null → use VAULT_MASTER_KEY from .env (base64). A KMS entry wraps the
    # per-user data keys through the provider SDK instead (key_id required).
    kms: KmsConfig | None = None
    # Seconds an unwrapped per-user data key may sit in process memory cache
    # (0 = keep for process lifetime; the cache is memory-only either way).
    cache_seconds: int = 0


class KmsConfig(BaseModel):
    provider: Literal["aws_kms", "gcp_kms"]
    key_id: str


class EmbeddingsConfig(BaseModel):
    provider: str
    model: str
    dimensions: int


class EmailConfig(BaseModel):
    provider: Literal["resend", "postmark", "brevo"]
    from_address: str


class WebConfig(BaseModel):
    search_provider: Literal["brave", "serpapi", "google_pse"]


class RuleMatch(BaseModel):
    tools: list[str] | None = None
    risk: Literal["safe", "moderate", "high"] | None = None
    amount_above_usd: Decimal | None = None
    merchants: list[str] | None = None
    source: Literal["user", "job", "any"] | None = "any"


class ApprovalRule(BaseModel):
    match: RuleMatch
    action: Literal["auto", "auto_and_log", "require_approval", "deny"]
    note: str | None = None


class LimitsDefaults(BaseModel):
    rules: list[ApprovalRule]
    fallback: Literal["auto", "auto_and_log", "require_approval", "deny"]


class PlanTier(BaseModel):
    monthly_included_usage_usd: Decimal
    hard_cap_usd: Decimal
    concurrent_tasks: int
    max_active_jobs: int
    autonomous_jobs: bool
    browser_tools: bool
    payments_enabled: bool
    stripe_price_id: str | None = None


class PlansConfig(BaseModel):
    tiers: dict[str, PlanTier]

    def tier(self, name: str) -> PlanTier:
        try:
            return self.tiers[name]
        except KeyError:
            raise ConfigError(
                f"plans.yaml: unknown plan tier '{name}' (have: {sorted(self.tiers)})"
            ) from None


class BillingConfig(BaseModel):
    enabled: bool = False
    allow_live: bool = False
    sdk_task_budget_usd: Decimal = Decimal("0.50")
    past_due_grace_days: int = 3


class PaymentsConfig(BaseModel):
    # No merchant-capable provider has been selected. This is an explicit
    # runtime kill switch, independent of subscription billing and plan tier.
    enabled: bool = False


class McpOAuth(BaseModel):
    client_id_env: str
    scopes: list[str] = []
    auth_url: str | None = None
    token_url: str | None = None


class McpServer(BaseModel):
    name: str
    enabled: bool = False
    oauth: McpOAuth | None = None


class McpConfig(BaseModel):
    servers: list[McpServer]


# --------------------------------------------------------------------------- #
# Aggregated settings
# --------------------------------------------------------------------------- #


class Settings(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    models: ModelsConfig
    model_prices: dict[str, ModelPrices]
    billing: BillingConfig = BillingConfig()
    payments: PaymentsConfig = PaymentsConfig()
    search_per_query_usd: Decimal
    limits: LimitsConfig
    sandbox: SandboxConfig
    scheduler: SchedulerConfig
    timezone_default: str
    quiet_hours: QuietHours
    browser: BrowserConfig
    vault: VaultConfig
    embeddings: EmbeddingsConfig
    email: EmailConfig
    web: WebConfig
    approval_rules: LimitsDefaults
    plans: PlansConfig
    mcp_servers: McpConfig
    secrets: Secrets

    def require(self, key: str) -> str:
        """Return a secret or fail loudly, naming the operator fix."""
        value = getattr(self.secrets, key, None)
        if not value:
            hint = _SECRET_HINTS.get(key, "see Part 0a in agent-build-spec-multiuser.md")
            raise ConfigError(f"Missing required setting {key.upper()}. Fix: {hint}")
        return value

    def plan_for(self, plan_tier: str) -> Any:
        return self.plans.tier(plan_tier)

    def masked(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in self.secrets.model_dump().items():
            if key in _NON_SECRET_KEYS:
                out[key] = value
            elif isinstance(value, str) and value:
                out[key] = _mask_dsn(value) if key == "database_url" else "[SET]"
            else:
                out[key] = "[MISSING]"
        return out

    def __repr__(self) -> str:  # pragma: no cover - repr cosmetics
        return f"Settings(secrets={self.masked()!r}, ...)"


def _mask_dsn(dsn: str) -> str:
    """Redact the password inside a Postgres DSN, keep the rest readable."""
    try:
        parsed = urlparse(dsn)
        if parsed.password is None:
            return dsn
        netloc = parsed.netloc.replace(f":{parsed.password}@", ":***@", 1)
        return urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        return "[SET]"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

_YAML_FILES: dict[str, str] = {
    "settings": "settings.yaml",
    "approval_rules": "limits.yaml",
    "plans": "plans.yaml",
    "mcp_servers": "mcp_servers.yaml",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"{path.name}: config file not found in {path.parent}")
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name}: invalid YAML — {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: expected a mapping at the top level")
    return data


def load_settings(
    config_dir: Path | str = CONFIG_DIR,
    env: dict[str, str] | None = None,
    load_env_file: bool = True,
) -> Settings:
    """Build Settings from YAML files + secrets.

    ``env`` (init kwargs) overrides environment variables, which override
    ``.env``. Unit tests pass explicit ``env`` for determinism.
    """
    config_dir = Path(config_dir)
    files = {key: _load_yaml(config_dir / fname) for key, fname in _YAML_FILES.items()}
    yaml_settings = files.pop("settings")  # settings.yaml fields live at top level

    secrets_kwargs: dict[str, Any] = dict(env or {})
    secrets_kwargs["_env_file"] = str(ENV_FILE) if (load_env_file and ENV_FILE.exists()) else None

    try:
        secrets = Secrets(**secrets_kwargs)
        settings = Settings(secrets=secrets, **yaml_settings, **files)
    except ValidationError as exc:
        raise ConfigError(f"config validation failed: {exc}") from exc

    if secrets.session_secret and len(secrets.session_secret) < 32:
        raise ConfigError("SESSION_SECRET: too short — use at least 32 bytes (openssl rand -base64 48)")

    for value in secrets.model_dump().values():
        if isinstance(value, str) and len(value) >= 8:
            clog.register_secret(value)
    return settings


settings: Settings = load_settings()


def reload() -> Settings:
    """Re-read the YAML config (secrets are not reloaded)."""
    global settings
    settings = load_settings(load_env_file=False)
    return settings
