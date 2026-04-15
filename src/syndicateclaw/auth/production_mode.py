"""Production mode configuration for fail-closed auth."""

from dataclasses import dataclass


@dataclass
class ProductionModeConfig:
    """
    Configuration for production authentication mode.

    When enabled, bearer tokens are rejected and only mTLS/client cert
    identity is accepted.
    """

    enabled: bool = False
    require_mtls: bool = False
    allow_bearer: bool = True

    @property
    def is_fail_closed(self) -> bool:
        """Returns True if authentication fails closed (denies on uncertainty)."""
        return self.enabled


def get_production_mode_config() -> ProductionModeConfig:
    """
    Load production mode config from environment.

    Environment variables:
        SYNDICATECLAW_PRODUCTION_MODE: Set to "true" to enable fail-closed auth
        SYNDICATECLAW_REQUIRE_MTLS: Set to "true" to require mTLS identity
        SYNDICATECLAW_ALLOW_BEARER: Set to "false" to disallow bearer tokens
    """
    import os

    env = os.environ.get

    return ProductionModeConfig(
        enabled=env("SYNDICATECLAW_PRODUCTION_MODE", "").lower() == "true",
        require_mtls=env("SYNDICATECLAW_REQUIRE_MTLS", "").lower() == "true",
        allow_bearer=env("SYNDICATECLAW_ALLOW_BEARER", "true").lower() == "true",
    )
