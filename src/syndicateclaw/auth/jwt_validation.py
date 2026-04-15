"""JWT validation with fail-closed behavior."""

from typing import Any

import structlog

from syndicateclaw.auth import decode_access_token, JWTError
from syndicateclaw.errors import AuthenticationError

logger = structlog.get_logger(__name__)


class JWTValidationMode:
    """
    JWT validation with configurable fail-closed behavior.

    When production_mode is enabled:
    - Invalid JWT -> raise AuthenticationError
    - Expired JWT -> raise AuthenticationError
    - Missing JWT -> raise AuthenticationError

    When production_mode is disabled:
    - Invalid JWT -> log warning, allow anonymous fallback
    """

    def __init__(self, production_mode: bool = False) -> None:
        """
        Initialize JWT validator.

        Args:
            production_mode: If True, fail closed on validation errors
        """
        self._production_mode = production_mode

    async def validate(
        self,
        token: str | None,
        *,
        secret_key: str | None = None,
        secondary_secret_key: str | None = None,
        algorithm: str | None = None,
        audience: str | None = None,
        oidc_jwks_url: str | None = None,
        issuer: str | None = None,
    ) -> dict[str, Any]:
        """
        Validate JWT and return claims.

        Args:
            token: JWT string or None
            secret_key: Secret key for HS256 validation
            secondary_secret_key: Secondary key for key rotation
            algorithm: JWT algorithm (default HS256)
            audience: Expected audience claim
            oidc_jwks_url: JWKS URL for RS256/OIDC validation
            issuer: Expected issuer claim

        Returns:
            Dict of JWT claims including 'sub' (actor)

        Raises:
            AuthenticationError: If validation fails in production mode
        """
        if token is None:
            if self._production_mode:
                raise AuthenticationError("No JWT provided in production mode")
            return {"sub": "anonymous"}

        try:
            claims = decode_access_token(
                token,
                secret_key=secret_key,
                secondary_secret_key=secondary_secret_key,
                algorithm=algorithm,
                audience=audience,
                oidc_jwks_url=oidc_jwks_url,
                issuer=issuer,
            )
            return claims
        except JWTError as e:
            if self._production_mode:
                raise AuthenticationError(f"JWT validation failed: {e}")
            logger.warning("auth.jwt_validation_failed", error=str(e))
            return {"sub": "anonymous"}
