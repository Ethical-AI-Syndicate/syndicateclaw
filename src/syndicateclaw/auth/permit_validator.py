"""Permit validation against syndicate-enterprise control plane."""

from dataclasses import dataclass

import httpx
import structlog

from syndicateclaw.errors import SyndicateClawError

logger = structlog.get_logger(__name__)


class PermitValidationError(SyndicateClawError):
    """Error during permit validation."""

    CODE = "PERMIT_VALIDATION_ERROR"
    HTTP_STATUS = 500


class ErrPermitExpired(SyndicateClawError):
    """Permit has expired."""

    CODE = "PERMIT_EXPIRED"
    HTTP_STATUS = 401


class ErrPermitNotValid(SyndicateClawError):
    """Permit is not valid."""

    CODE = "PERMIT_NOT_VALID"
    HTTP_STATUS = 403


@dataclass
class PermitValidationResult:
    """Result of permit validation."""

    valid: bool
    expired: bool = False
    reason: str | None = None


@dataclass
class PermitValidatorConfig:
    """
    Configuration for permit validation against syndicate-enterprise.
    """

    permit_api_url: str
    timeout_seconds: float = 5.0
    fail_closed: bool = True
    production_mode: bool = False

    @property
    def is_fail_closed(self) -> bool:
        return self.fail_closed


class PermitValidator:
    """
    Validates permits against the syndicate-enterprise control plane.

    SGE REST contract:
    - Endpoint: POST /v1/permits/validate
    - Body: {"permit_token": "..."}
    - Response: {"valid": bool, "expired": bool, "reason?: string}

    Fail-closed behavior:
    - Network error -> PermitValidationError (caller should deny)
    - valid=false, expired=true -> ErrPermitExpired
    - valid=false, expired=false -> ErrPermitNotValid
    - HTTP 5xx -> fail_closed=True -> error; fail_closed=False -> warn and allow
    """

    def __init__(self, config: PermitValidatorConfig) -> None:
        """
        Initialize permit validator.

        Args:
            config: Permit validation configuration
        """
        self._config = config
        self._http = httpx.AsyncClient(timeout=config.timeout_seconds)

    async def validate(self, permit_token: str) -> PermitValidationResult:
        """
        Validate a permit against the syndicate-enterprise API.

        Args:
            permit_token: The permit token to validate

        Returns:
            PermitValidationResult with valid=True if permit is accepted

        Raises:
            ErrPermitExpired: If permit has expired
            ErrPermitNotValid: If permit is not valid
            PermitValidationError: If validation cannot be completed (fail-closed)
        """
        if self._config.production_mode and permit_token.startswith("Bearer "):
            raise ErrPermitNotValid("Bearer tokens not accepted in production mode")

        payload = {"permit_token": permit_token}

        try:
            response = await self._http.post(
                f"{self._config.permit_api_url}/v1/permits/validate",
                json=payload,
            )

            if response.status_code == 200:
                data = response.json()
                result = PermitValidationResult(
                    valid=data.get("valid", False),
                    expired=data.get("expired", False),
                    reason=data.get("reason"),
                )
                if not result.valid:
                    if result.expired:
                        raise ErrPermitExpired(result.reason or "permit expired")
                    raise ErrPermitNotValid(result.reason or "permit not valid")
                return result
            elif 400 <= response.status_code < 500:
                raise ErrPermitNotValid(f"HTTP {response.status_code}: {response.text}")
            else:
                if self._config.fail_closed:
                    raise PermitValidationError(f"Permit API server error: {response.status_code}")
                logger.warning(
                    "permit_validation.server_error",
                    status=response.status_code,
                )
                return PermitValidationResult(valid=True)

        except httpx.TimeoutException as e:
            if self._config.fail_closed:
                raise PermitValidationError(f"Permit validation timed out: {e}")
            logger.warning("permit_validation.timeout")
            return PermitValidationResult(valid=True)
        except httpx.RequestError as e:
            if self._config.fail_closed:
                raise PermitValidationError(f"Permit validation request failed: {e}")
            logger.warning("permit_validation.request_error", error=str(e))
            return PermitValidationResult(valid=True)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._http.aclose()
