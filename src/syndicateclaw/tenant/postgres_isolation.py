"""Tenant-isolated Postgres operations."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from sqlalchemy import text

_tenant_context: ContextVar[str | None] = ContextVar("tenant_id", default=None)


class TenantContext:
    """
    Thread-local/context-local tenant context.

    Use as a context manager or with `with TenantContext(tenant_id):`
    """

    @classmethod
    def get_tenant_id(cls) -> str | None:
        """Get current tenant ID from context."""
        return _tenant_context.get()

    @classmethod
    def set_tenant_id(cls, tenant_id: str | None) -> None:
        """Set current tenant ID in context."""
        _tenant_context.set(tenant_id)

    @classmethod
    def with_tenant(cls, tenant_id: str):
        """Context manager for tenant-scoped operations."""
        token = cls.set(tenant_id)
        try:
            yield
        finally:
            cls.reset(token)

    @classmethod
    def set(cls, tenant_id: str | None):
        """Set tenant ID and return token for reset."""
        return _tenant_context.set(tenant_id)

    @classmethod
    def reset(cls, token):
        """Reset to previous value."""
        _tenant_context.reset(token)


def get_current_tenant_id() -> str | None:
    """Get the current tenant ID from context."""
    return TenantContext.get_tenant_id()


def require_tenant_id() -> str:
    """Get current tenant ID or raise error."""
    tenant_id = get_current_tenant_id()
    if not tenant_id:
        from syndicateclaw.errors import TenantBindingError

        raise TenantBindingError("No tenant in context")
    return tenant_id


class TenantPostgresIsolation:
    """
    Provides tenant-isolated Postgres operations.

    In multi-schema deployments, each tenant has their own Postgres schema.
    """

    def __init__(self, session_factory: Any, tenant_id: str) -> None:
        self._session_factory = session_factory
        self._tenant_id = tenant_id
        self._search_path: list[str] = []

    async def __aenter__(self) -> "TenantPostgresIsolation":
        """Set schema search path on context entry."""
        await self._set_search_path()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Restore schema search path on context exit."""
        await self._reset_search_path()

    async def _set_search_path(self) -> None:
        """Set Postgres search path to tenant's schema."""
        schema_name = f"tenant_{self._tenant_id}"

        async with self._session_factory() as session:
            result = await session.execute(text("SHOW search_path"))
            self._search_path = [row[0] for row in result.fetchall()]

            await session.execute(text(f"SET search_path TO {schema_name}"))

    async def _reset_search_path(self) -> None:
        """Restore original search path."""
        if self._search_path:
            async with self._session_factory() as session:
                path_str = ", ".join(self._search_path)
                await session.execute(text(f"SET search_path TO {path_str}"))
