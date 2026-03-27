from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from syndicateclaw.api.dependencies import get_agent_service, get_current_actor
from syndicateclaw.services.agent_service import (
    AgentConflictError,
    AgentNotFoundError,
    AgentOwnershipError,
)

router = APIRouter(prefix="/api/v1/agents", tags=["agents"])

DEP_CURRENT_ACTOR = Depends(get_current_actor)
DEP_AGENT_SERVICE = Depends(get_agent_service)
Q_NAMESPACE = Query(None)
Q_CAPABILITY = Query(None)
Q_STATUS = Query(None)
Q_NAME = Query(None)


class AgentRegisterRequest(BaseModel):
    name: str
    description: str | None = None
    namespace: str
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    capabilities: list[str] | None = None
    metadata: dict[str, Any] | None = None


class AgentResponse(BaseModel):
    model_config = {"from_attributes": True, "populate_by_name": True}

    id: str
    name: str
    description: str | None
    namespace: str
    capabilities: list[str]
    metadata: dict[str, Any] = Field(alias="metadata_")
    status: str
    registered_by: str
    heartbeat_at: datetime | None = None
    deregistered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def register_agent(
    body: AgentRegisterRequest,
    actor: str = DEP_CURRENT_ACTOR,
    agent_service: Any = DEP_AGENT_SERVICE,
) -> Any:
    try:
        return await agent_service.register(
            name=body.name,
            capabilities=body.capabilities,
            namespace=body.namespace,
            metadata=body.metadata,
            actor=actor,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except AgentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    namespace: str | None = Q_NAMESPACE,
    capability: str | None = Q_CAPABILITY,
    status_filter: str | None = Q_STATUS,
    name: str | None = Q_NAME,
    actor: str = DEP_CURRENT_ACTOR,
    agent_service: Any = DEP_AGENT_SERVICE,
) -> list[Any]:
    _ = actor
    rows = await agent_service.discover(
        namespace=namespace,
        capability=capability,
        status=status_filter,
        name=name,
    )
    return list(rows)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    actor: str = DEP_CURRENT_ACTOR,
    agent_service: Any = DEP_AGENT_SERVICE,
) -> Any:
    _ = actor
    try:
        return await agent_service.get(agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    body: AgentUpdateRequest,
    actor: str = DEP_CURRENT_ACTOR,
    agent_service: Any = DEP_AGENT_SERVICE,
) -> Any:
    try:
        return await agent_service.update(
            agent_id,
            actor,
            name=body.name,
            capabilities=body.capabilities,
            metadata=body.metadata,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AgentConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{agent_id}", response_model=AgentResponse)
async def deregister_agent(
    agent_id: str,
    actor: str = DEP_CURRENT_ACTOR,
    agent_service: Any = DEP_AGENT_SERVICE,
) -> Any:
    try:
        return await agent_service.deregister(agent_id, actor)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/{agent_id}/heartbeat", response_model=AgentResponse)
async def heartbeat_agent(
    agent_id: str,
    actor: str = DEP_CURRENT_ACTOR,
    agent_service: Any = DEP_AGENT_SERVICE,
) -> Any:
    try:
        return await agent_service.heartbeat(agent_id, actor)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AgentOwnershipError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
