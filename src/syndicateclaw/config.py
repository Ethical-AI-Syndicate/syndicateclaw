from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_env_file() -> str | list[str]:
    """Resolve the .env file path from SYNDICATECLAW_ENV.

    Lookup order:
      1. .env.{SYNDICATECLAW_ENV}  (e.g. .env.staging)
      2. .env                       (generic fallback)

    This allows multiple environments (dev, staging, prod) to coexist
    on the same host with isolated databases, Redis logical DBs, and
    API ports.
    """
    env_name = os.environ.get("SYNDICATECLAW_ENV", "").strip().lower()
    if env_name:
        specific = Path(f".env.{env_name}")
        if specific.exists():
            return [str(specific), ".env"]
    return ".env"


class Settings(BaseSettings):
    """Application-wide configuration loaded from env vars / .env file.

    Set SYNDICATECLAW_ENV to select environment: dev, staging, prod.
    This loads .env.{env} with .env as fallback.
    """

    model_config = SettingsConfigDict(
        env_prefix="SYNDICATECLAW_",
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_url: str = Field(..., description="Async PostgreSQL DSN (e.g. postgresql+asyncpg://…)")
    redis_url: str = Field(default="redis://localhost:6379/0", description="Redis connection URL")
    api_host: str = Field(default="0.0.0.0", description="Host to bind the API server")
    api_port: int = Field(default=8000, ge=1, le=65535, description="Port for the API server")
    log_level: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, …)")
    otel_endpoint: str | None = Field(
        default=None, description="OpenTelemetry collector gRPC endpoint"
    )

    approval_timeout_seconds: int = Field(
        default=3600, ge=1, description="Default timeout for approval requests"
    )
    memory_default_ttl_seconds: int = Field(
        default=86400 * 30, ge=1, description="Default TTL for memory records (30 days)"
    )
    memory_max_value_bytes: int = Field(
        default=1_048_576, ge=1,
        description="Maximum size in bytes for a memory record value (1MB default)",
    )
    memory_max_key_length: int = Field(
        default=256, ge=1,
        description="Maximum length of a memory key string",
    )
    memory_max_namespace_length: int = Field(
        default=128, ge=1,
        description="Maximum length of a memory namespace string",
    )
    max_workflow_depth: int = Field(
        default=10, ge=1, description="Maximum nesting depth for sub-workflows"
    )
    max_concurrent_runs: int = Field(
        default=100, ge=1, description="Maximum concurrent workflow runs"
    )
    rate_limit_requests: int = Field(
        default=100, ge=1, description="Max requests per actor per rate window"
    )
    rate_limit_window_seconds: int = Field(
        default=60, ge=1, description="Rate limit sliding window in seconds"
    )
    rate_limit_burst: int = Field(
        default=20, ge=1, description="Max burst requests allowed above sustained rate"
    )
    rate_limit_strict: bool = Field(
        default=False,
        description="If True, /readyz fails when rate limiting is unavailable (Redis down). "
        "If False (default), rate limiting degrades open.",
    )

    cors_origins: list[str] = Field(default_factory=list, description="Allowed CORS origins")
    secret_key: str = Field(..., description="Secret key for signing tokens and sessions")
    environment: str = Field(
        default="production",
        description="Deployment environment (development, staging, production). "
        "Anonymous auth fallback is only allowed in development/test.",
    )
    require_asymmetric_signing: bool = Field(
        default=False,
        description="If True, system refuses to start without an Ed25519 signing key. "
        "Set SYNDICATECLAW_ED25519_PRIVATE_KEY_PATH to the PEM file path.",
    )
    ed25519_private_key_path: str | None = Field(
        default=None,
        description="Path to Ed25519 private key PEM file for asymmetric evidence signing.",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm. 'HS256' for symmetric (default), "
        "'EdDSA' for Ed25519 asymmetric (requires ed25519_private_key_path).",
    )
    providers_yaml_path: str | None = Field(
        default=None,
        description=(
            "Optional path to providers.yaml (Phase 1 provider topology; YAML authoritative)."
        ),
    )

    models_dev_feed_url: str | None = Field(
        default=None,
        description="Optional HTTPS URL for models.dev-style catalog JSON (enriched merge only).",
    )
    models_dev_max_fetch_bytes: int = Field(
        default=10_485_760,
        ge=1024,
        description="Hard cap on models.dev fetch body size (bytes).",
    )
    models_dev_fetch_timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        description="Connect+read timeout for models.dev HTTP fetch.",
    )
    models_dev_max_redirects: int = Field(
        default=8,
        ge=0,
        le=32,
        description="Maximum HTTP redirects; each target is SSRF-checked after redirect.",
    )
    models_dev_allowed_host_suffixes: list[str] = Field(
        default_factory=lambda: ["models.dev"],
        description="Only these host suffixes (e.g. models.dev, sub.models.dev) may be fetched.",
    )
    rbac_enforcement_enabled: bool = Field(
        default=True,
        description="When True, RBAC decisions deny before the route runs (403). "
        "When False, RBAC runs in shadow mode only.",
    )
    allow_unscoped_keys: bool = Field(
        default=True,
        description=(
            "When False, API keys without explicit scopes are rejected with 401. "
            "Default True preserves backward compatibility for legacy unscoped keys."
        ),
    )
    streaming_token_ttl_seconds: int = Field(
        default=300,
        ge=1,
        description="Single-use streaming token TTL in seconds.",
    )
    agent_heartbeat_check_interval: int = Field(
        default=30,
        ge=1,
        description="Background poll interval in seconds for stale agent heartbeat checks.",
    )
    agent_heartbeat_timeout_seconds: int = Field(
        default=60,
        ge=1,
        description=(
            "Heartbeat staleness timeout in seconds before ONLINE "
            "agents are marked OFFLINE."
        ),
    )
    message_max_hops: int = Field(
        default=10,
        ge=1,
        description="Maximum relay hops for agent messages before forced termination.",
    )
    runtime_enabled: bool = Field(
        default=False,
        description="When True, register experimental runtime/skill routes (Phase 1).",
    )
    jwt_audience: str | None = Field(
        default=None,
        description="If set, JWTs must include this aud claim.",
    )
    jwt_secondary_secret_key: str | None = Field(
        default=None,
        description="Optional second HS256 secret for key rotation (tried after primary).",
    )
