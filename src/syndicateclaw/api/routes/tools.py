from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from syndicateclaw.api.dependencies import (
    get_current_actor,
    get_db_session,
    get_tool_executor,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])

Q_RISK_LEVEL = Query(None)
Q_OFFSET = Query(0, ge=0)
Q_LIMIT = Query(50, ge=1, le=200)
DEP_CURRENT_ACTOR = Depends(get_current_actor)
DEP_DB_SESSION = Depends(get_db_session)
DEP_TOOL_EXECUTOR = Depends(get_tool_executor)

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class ToolResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    description: str | None = None
    version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    risk_level: str
    required_permissions: list[str] | Any = Field(default_factory=lambda: [])
    side_effects: list[str] | Any = Field(default_factory=lambda: [])
    timeout_seconds: int
    max_retries: int
    idempotent: bool
    enabled: bool
    owner: str | None = None
    created_at: datetime
    updated_at: datetime


class ExecuteToolRequest(BaseModel):
    input_data: dict[str, Any] = Field(default_factory=dict)


class ExecuteToolResponse(BaseModel):
    tool_name: str
    status: str
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[ToolResponse])
async def list_tools(
    risk_level: str | None = Q_RISK_LEVEL,
    offset: int = Q_OFFSET,
    limit: int = Q_LIMIT,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> list[Any]:
    from sqlalchemy import select

    from syndicateclaw.db.models import Tool as ToolModel

    stmt = select(ToolModel).where(ToolModel.enabled.is_(True))
    if risk_level:
        stmt = stmt.where(ToolModel.risk_level == risk_level)
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{tool_name}", response_model=ToolResponse)
async def get_tool(
    tool_name: str,
    actor: str = DEP_CURRENT_ACTOR,
    db: AsyncSession = DEP_DB_SESSION,
) -> Any:
    from sqlalchemy import select

    from syndicateclaw.db.models import Tool as ToolModel

    stmt = select(ToolModel).where(ToolModel.name == tool_name)
    result = await db.execute(stmt)
    tool = result.scalar_one_or_none()
    if tool is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
    return tool


@router.post("/{tool_name}/execute", response_model=ExecuteToolResponse)
async def execute_tool(
    tool_name: str,
    body: ExecuteToolRequest,
    actor: str = DEP_CURRENT_ACTOR,
    executor: Any = DEP_TOOL_EXECUTOR,
) -> ExecuteToolResponse:
    import time

    from syndicateclaw.tools.executor import (
        ToolDeniedError,
        ToolExecutionError,
        ToolNotFoundError,
        ToolTimeoutError,
    )

    t0 = time.monotonic()
    try:
        from syndicateclaw.orchestrator.engine import ExecutionContext

        ctx = ExecutionContext(run_id=f"adhoc-{actor}")
        output = await executor.execute(tool_name, body.input_data, ctx)
        duration_ms = int((time.monotonic() - t0) * 1000)
        return ExecuteToolResponse(
            tool_name=tool_name,
            status="completed",
            output=output,
            duration_ms=duration_ms,
        )
    except ToolNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found"
        ) from None
    except ToolDeniedError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except ToolTimeoutError as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        return ExecuteToolResponse(
            tool_name=tool_name,
            status="timed_out",
            error=str(exc),
            duration_ms=duration_ms,
        )
    except ToolExecutionError as exc:
        duration_ms = int((time.monotonic() - t0) * 1000)
        return ExecuteToolResponse(
            tool_name=tool_name,
            status="failed",
            error=str(exc),
            duration_ms=duration_ms,
        )
