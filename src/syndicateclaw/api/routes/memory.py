from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from syndicateclaw.api.decorators.quota import enforce_quota, json_value_byte_size
from syndicateclaw.api.dependencies import (
    get_actor_org,
    get_current_actor,
    get_db_session,
)
from syndicateclaw.models import MemoryDeletionStatus, MemoryType
from syndicateclaw.services.organization_service import (
    add_storage_bytes_used,
    count_memory_records_for_org,
    get_storage_bytes_used,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])

DEP_CURRENT_ACTOR = Depends(get_current_actor)
DEP_DB_SESSION = Depends(get_db_session)
DEP_ACTOR_ORG = Depends(get_actor_org)
Q_MEMORY_TYPE = Query(None)
Q_OFFSET = Query(0, ge=0)
Q_LIMIT = Query(50, ge=1, le=200)

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class WriteMemoryRequest(BaseModel):
    namespace: str
    key: str
    value: Any
    memory_type: MemoryType
    source: str
    confidence: float = 1.0
    ttl_seconds: int | None = None
    access_policy: str = "default"
    tags: dict[str, str] = Field(default_factory=dict)
    lineage: dict[str, Any] = Field(default_factory=dict)


class UpdateMemoryRequest(BaseModel):
    value: Any | None = None
    confidence: float | None = None
    ttl_seconds: int | None = None
    tags: dict[str, str] | None = None


class MemoryResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    namespace: str
    key: str
    value: Any
    memory_type: str
    source: str | None = None
    actor: str | None = None
    confidence: float | None = None
    access_policy: str = "private"
    lineage: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: int | None = None
    expires_at: datetime | None = None
    deletion_status: str = "active"
    tags: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class MemoryLineageResponse(BaseModel):
    record_id: str
    chain: list[MemoryResponse]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def write_memory(
    body: WriteMemoryRequest,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
    actor_org: Any = DEP_ACTOR_ORG,
) -> Any:
    from datetime import UTC, timedelta

    from syndicateclaw.db.models import MemoryRecord as MRModel

    if actor_org is not None and body.namespace != actor_org.namespace:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-namespace access requires impersonation",
        )

    await enforce_quota(actor_org, db, "max_memory_records", count_memory_records_for_org)
    value_bytes = json_value_byte_size(
        body.value if isinstance(body.value, dict) else {"_value": body.value}
    )
    if actor_org is not None:
        quotas = actor_org.quotas or {}
        limit_bytes = quotas.get("storage_limit_bytes", float("inf"))
        current_bytes = await get_storage_bytes_used(db, actor_org.id)
        if current_bytes + value_bytes > limit_bytes:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"error": "storage_quota_exceeded"},
            )

    expires_at = None
    if body.ttl_seconds is not None:
        expires_at = datetime.now(UTC) + timedelta(seconds=body.ttl_seconds)

    record = MRModel(
        namespace=body.namespace,
        key=body.key,
        value=body.value if isinstance(body.value, dict) else {"_value": body.value},
        memory_type=body.memory_type.value,
        source=body.source,
        actor=actor,
        confidence=body.confidence,
        lineage=body.lineage,
        ttl_seconds=body.ttl_seconds,
        expires_at=expires_at,
        access_policy=body.access_policy,
        tags=body.tags,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    if actor_org is not None:
        await add_storage_bytes_used(db, actor_org.id, value_bytes)
    logger.info("memory.written", namespace=body.namespace, key=body.key)
    return record


@router.get("/{namespace}/{key}", response_model=MemoryResponse)
async def read_memory(
    namespace: str,
    key: str,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> Any:
    from sqlalchemy import select

    from syndicateclaw.db.models import MemoryRecord as MRModel

    stmt = select(MRModel).where(
        MRModel.namespace == namespace,
        MRModel.key == key,
        MRModel.deletion_status == MemoryDeletionStatus.ACTIVE.value,
    )
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found"
        )

    from syndicateclaw.memory.service import MemoryService
    domain_record = MemoryService._db_to_domain(record)
    if not MemoryService._check_access_policy(domain_record, actor):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found"
        )

    return record


@router.get("/{namespace}", response_model=list[MemoryResponse])
async def search_memory(
    namespace: str,
    memory_type: str | None = Q_MEMORY_TYPE,
    offset: int = Q_OFFSET,
    limit: int = Q_LIMIT,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> list[Any]:
    from sqlalchemy import select

    from syndicateclaw.db.models import MemoryRecord as MRModel

    stmt = select(MRModel).where(
        MRModel.namespace == namespace,
        MRModel.deletion_status == MemoryDeletionStatus.ACTIVE.value,
    )
    if memory_type:
        stmt = stmt.where(MRModel.memory_type == memory_type)
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    rows = list(result.scalars().all())

    from syndicateclaw.memory.service import MemoryService
    filtered = []
    for row in rows:
        domain_record = MemoryService._db_to_domain(row)
        if MemoryService._check_access_policy(domain_record, actor):
            filtered.append(row)
    return filtered


@router.put("/{record_id}", response_model=MemoryResponse)
async def update_memory(
    record_id: str,
    body: UpdateMemoryRequest,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> Any:
    from syndicateclaw.db.models import MemoryRecord as MRModel

    record = await db.get(MRModel, record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found"
        )

    from syndicateclaw.memory.service import MemoryService
    domain_record = MemoryService._db_to_domain(record)
    if not MemoryService._check_access_policy(domain_record, actor):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found"
        )

    if record.deletion_status != MemoryDeletionStatus.ACTIVE.value:
        raise HTTPException(
            status_code=status.HTTP_410_GONE, detail="Memory record has been deleted"
        )

    if body.value is not None:
        record.value = body.value if isinstance(body.value, dict) else {"_value": body.value}
    if body.confidence is not None:
        record.confidence = body.confidence
    if body.ttl_seconds is not None:
        record.ttl_seconds = body.ttl_seconds
        from datetime import UTC, timedelta

        record.expires_at = datetime.now(UTC) + timedelta(seconds=body.ttl_seconds)
    if body.tags is not None:
        record.tags = body.tags

    await db.flush()
    await db.refresh(record)
    logger.info("memory.updated", record_id=record_id)
    return record


@router.delete(
    "/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def delete_memory(
    record_id: str,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> None:
    from datetime import UTC

    from syndicateclaw.db.models import MemoryRecord as MRModel

    record = await db.get(MRModel, record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found"
        )

    from syndicateclaw.memory.service import MemoryService
    domain_record = MemoryService._db_to_domain(record)
    if not MemoryService._check_access_policy(domain_record, actor):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found"
        )

    record.deletion_status = MemoryDeletionStatus.MARKED_FOR_DELETION.value
    record.deleted_at = datetime.now(UTC)
    await db.flush()
    logger.info("memory.soft_deleted", record_id=record_id)


@router.get("/{record_id}/lineage", response_model=MemoryLineageResponse)
async def get_memory_lineage(
    record_id: str,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> MemoryLineageResponse:
    from syndicateclaw.db.models import MemoryRecord as MRModel

    record = await db.get(MRModel, record_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found"
        )

    from syndicateclaw.memory.service import MemoryService
    domain_record = MemoryService._db_to_domain(record)
    if not MemoryService._check_access_policy(domain_record, actor):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Memory record not found"
        )

    chain: list[Any] = [record]
    lineage = record.lineage or {}
    parent_ids: list[str] = lineage.get("parent_ids", [])

    visited = {record_id}
    while parent_ids:
        next_parents: list[str] = []
        for pid in parent_ids:
            if pid in visited:
                continue
            visited.add(pid)
            parent = await db.get(MRModel, pid)
            if parent is not None:
                chain.append(parent)
                p_lineage = parent.lineage or {}
                next_parents.extend(p_lineage.get("parent_ids", []))
        parent_ids = next_parents

    return MemoryLineageResponse(record_id=record_id, chain=chain)
