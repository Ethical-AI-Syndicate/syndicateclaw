"""Quota enforcement helpers for organization-scoped resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from syndicateclaw.db.models import Organization


async def enforce_quota(
    actor_org: Organization | None,
    session: AsyncSession,
    quota_field: str,
    count_fn: Callable[[AsyncSession, str], Awaitable[int]],
) -> None:
    if actor_org is None:
        return
    quotas = actor_org.quotas or {}
    limit = quotas.get(quota_field, float("inf"))
    if limit == float("inf"):
        return
    current = await count_fn(session, actor_org.namespace)
    if current >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "quota_exceeded",
                "quota": quota_field,
                "limit": limit,
                "current": current,
            },
        )


def json_value_byte_size(value: Any) -> int:
    import json

    return len(json.dumps(value, default=str).encode("utf-8"))
