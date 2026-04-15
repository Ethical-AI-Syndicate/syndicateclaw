"""SyndicateClaw error sentinels."""


class SyndicateClawError(Exception):
    """Base exception for all syndicateclaw errors."""

    CODE: str = "INTERNAL_ERROR"
    HTTP_STATUS: int = 500

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict:
        """Convert to error response dict."""
        return {
            "error": {
                "code": self.CODE,
                "message": self.message,
                "details": self.details,
            }
        }


class ValidationError(SyndicateClawError):
    """Input validation failed."""

    CODE = "VALIDATION_ERROR"
    HTTP_STATUS = 400


class AuthenticationError(SyndicateClawError):
    """Authentication failed."""

    CODE = "AUTHENTICATION_ERROR"
    HTTP_STATUS = 401


class AuthorizationError(SyndicateClawError):
    """Authorization/permission denied."""

    CODE = "AUTHORIZATION_ERROR"
    HTTP_STATUS = 403


class NotFoundError(SyndicateClawError):
    """Resource not found."""

    CODE = "NOT_FOUND"
    HTTP_STATUS = 404


class ConflictError(SyndicateClawError):
    """Resource conflict (duplicate, etc.)."""

    CODE = "CONFLICT"
    HTTP_STATUS = 409


class PolicyDeniedError(SyndicateClawError):
    """Policy engine denied the request."""

    CODE = "POLICY_DENIED"
    HTTP_STATUS = 403


class ApprovalRequiredError(SyndicateClawError):
    """Action requires approval."""

    CODE = "APPROVAL_REQUIRED"
    HTTP_STATUS = 403


class RateLimitError(SyndicateClawError):
    """Rate limit exceeded."""

    CODE = "RATE_LIMIT_EXCEEDED"
    HTTP_STATUS = 429


class SSRFBlockedError(SyndicateClawError):
    """URL blocked by SSRF protection."""

    CODE = "SSRF_BLOCKED"
    HTTP_STATUS = 400


class TenantBindingError(SyndicateClawError):
    """Tenant binding validation failed."""

    CODE = "TENANT_BINDING_ERROR"
    HTTP_STATUS = 403


class BootstrapError(SyndicateClawError):
    """Bootstrap/initialization error."""

    CODE = "BOOTSTRAP_ERROR"
    HTTP_STATUS = 500


class MigrationError(SyndicateClawError):
    """Database migration error."""

    CODE = "MIGRATION_ERROR"
    HTTP_STATUS = 500


class IntegrityCheckError(SyndicateClawError):
    """Integrity check failed."""

    CODE = "INTEGRITY_CHECK_ERROR"
    HTTP_STATUS = 500
