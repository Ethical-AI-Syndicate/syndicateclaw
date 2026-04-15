"""Tenant binding modes and validation."""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TenantBindingMode(Enum):
    """
    Tenant binding modes with increasing strictness.

    HeaderOnly - Trust X-Tenant-ID header (for internal services behind trusted proxy)
    IdentityBound - Bind tenant to authenticated identity (from mTLS cert or JWT claim)
    Strict - Require both header AND identity match, with validation
    """

    HEADER_ONLY = "header_only"
    IDENTITY_BOUND = "identity_bound"
    STRICT = "strict"


@dataclass
class TenantBinding:
    """
    Tenant binding configuration for a request or resource.

    Attributes:
        mode: The binding mode determining how tenant is determined
        tenant_id: The tenant identifier
        actor: The actor within the tenant
        scope_type: Type of scope (org, workspace, namespace)
        scope_id: Identifier within the scope type
    """

    mode: TenantBindingMode
    tenant_id: str
    actor: str
    scope_type: str = "org"
    scope_id: str | None = None

    @property
    def is_strict(self) -> bool:
        """Returns True if in strict mode."""
        return self.mode == TenantBindingMode.STRICT

    @property
    def requires_header(self) -> bool:
        """Returns True if header is required."""
        return self.mode in (TenantBindingMode.HEADER_ONLY, TenantBindingMode.STRICT)

    @property
    def requires_identity(self) -> bool:
        """Returns True if identity is required."""
        return self.mode in (TenantBindingMode.IDENTITY_BOUND, TenantBindingMode.STRICT)


class TenantBindingError(Exception):
    """Error validating tenant binding."""


class TenantBindingValidator:
    """
    Validates tenant bindings against incoming requests.

    Ensures that:
    1. Header-provided tenant IDs are validated
    2. Identity-derived tenants are consistent
    3. Strict mode requires both and validates match
    """

    def __init__(self, mode: TenantBindingMode = TenantBindingMode.IDENTITY_BOUND) -> None:
        self._mode = mode

    def validate_request(
        self,
        headers: dict[str, str],
        identity: Any | None,
        jwt_claims: dict[str, Any] | None,
    ) -> TenantBinding:
        """
        Validate and extract tenant binding from request.

        Args:
            headers: HTTP headers (may include X-Tenant-ID)
            identity: mTLS identity if present
            jwt_claims: JWT claims if present

        Returns:
            TenantBinding with validated tenant information

        Raises:
            TenantBindingError: If validation fails
        """
        header_tenant = headers.get("X-Tenant-ID")
        identity_tenant = self._extract_tenant_from_identity(identity)
        jwt_tenant = self._extract_tenant_from_jwt(jwt_claims)

        if self._mode == TenantBindingMode.HEADER_ONLY:
            if not header_tenant:
                raise TenantBindingError("X-Tenant-ID header required")
            return TenantBinding(
                mode=self._mode,
                tenant_id=header_tenant,
                actor=self._extract_actor(identity, jwt_claims),
            )

        elif self._mode == TenantBindingMode.IDENTITY_BOUND:
            tenant = identity_tenant or jwt_tenant
            if not tenant:
                raise TenantBindingError("No tenant identity available")
            return TenantBinding(
                mode=self._mode,
                tenant_id=tenant,
                actor=self._extract_actor(identity, jwt_claims),
            )

        else:  # STRICT
            if not header_tenant:
                raise TenantBindingError("X-Tenant-ID header required in strict mode")
            identity_tenant = identity_tenant or jwt_tenant
            if not identity_tenant:
                raise TenantBindingError("No tenant identity in strict mode")
            if header_tenant != identity_tenant:
                raise TenantBindingError(
                    f"Tenant mismatch: header={header_tenant}, identity={identity_tenant}"
                )
            return TenantBinding(
                mode=self._mode,
                tenant_id=header_tenant,
                actor=self._extract_actor(identity, jwt_claims),
                scope_type="org",
                scope_id=header_tenant,
            )

    def _extract_tenant_from_identity(self, identity: Any | None) -> str | None:
        """Extract tenant from mTLS identity."""
        if identity is None:
            return None
        if hasattr(identity, "subject_dn") and identity.subject_dn:
            return self._parse_org_from_dn(identity.subject_dn)
        return None

    def _extract_tenant_from_jwt(self, claims: dict[str, Any] | None) -> str | None:
        """Extract tenant from JWT claims."""
        if claims is None:
            return None
        return claims.get("org_id") or claims.get("tenant_id")

    def _extract_actor(self, identity: Any | None, jwt_claims: dict[str, Any] | None) -> str:
        """Extract actor from identity or JWT."""
        if identity and hasattr(identity, "subject_dn") and identity.subject_dn:
            return self._dn_to_actor(identity.subject_dn)
        if jwt_claims:
            return jwt_claims.get("sub", "unknown")
        return "anonymous"

    def _parse_org_from_dn(self, dn: str) -> str | None:
        """Parse organization from Distinguished Name."""
        import re

        match = re.search(r"O=([^,]+)", dn)
        return match.group(1) if match else None

    def _dn_to_actor(self, dn: str) -> str:
        """Convert DN to actor identifier."""
        import re

        match = re.search(r"CN=([^,]+)", dn, re.IGNORECASE)
        if match:
            return match.group(1).lower().replace(" ", "_")
        return "unknown"
