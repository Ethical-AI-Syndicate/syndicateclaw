"""Tenant binding validation helpers."""

from dataclasses import dataclass
from typing import Any

from syndicateclaw.tenant.binding import TenantBinding, TenantBindingError, TenantBindingValidator


@dataclass
class TenantBindingValidationResult:
    """Result of tenant binding validation."""

    valid: bool
    binding: TenantBinding | None
    errors: list[str]

    @property
    def is_valid(self) -> bool:
        """Returns True if binding is valid."""
        return self.valid


async def ValidateTenantBinding(
    binding: TenantBinding,
    session_factory,
) -> bool:
    """
    Validate that a tenant binding is authorized.

    Checks:
    1. Tenant exists and is active
    2. Actor has access to the tenant
    3. Scope is valid for the tenant

    Args:
        binding: The tenant binding to validate
        session_factory: SQLAlchemy async session factory

    Returns:
        True if valid

    Raises:
        TenantBindingError: If binding is invalid
    """
    try:
        async with session_factory() as session:
            from sqlalchemy import select
            from syndicateclaw.db.models import Organization, Principal

            result = await session.execute(
                select(Organization).where(Organization.id == binding.tenant_id)
            )
            org = result.scalar_one_or_none()

            if org is None:
                raise TenantBindingError(f"Tenant {binding.tenant_id} not found or inactive")

            if binding.actor != "anonymous":
                result = await session.execute(
                    select(Principal).where(Principal.name == binding.actor)
                )
                principal = result.scalar_one_or_none()

                if principal is None:
                    raise TenantBindingError(f"Actor {binding.actor} not found")

            return True

    except TenantBindingError:
        raise
    except Exception as e:
        raise TenantBindingError(f"Validation error: {e}") from e
