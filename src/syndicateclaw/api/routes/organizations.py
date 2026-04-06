from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from syndicateclaw.api.dependencies import get_current_actor, get_db_session
from syndicateclaw.db.models import Organization
from syndicateclaw.services.organization_service import OrganizationService

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/organizations", tags=["organizations"])

DEP_ACTOR = Depends(get_current_actor)
DEP_DB = Depends(get_db_session)


class CreateOrganizationRequest(BaseModel):
    name: str = Field(..., min_length=1)
    display_name: str = Field(..., min_length=1)


class UpdateOrganizationRequest(BaseModel):
    display_name: str | None = None
    settings: dict[str, Any] | None = None


class OrganizationResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    display_name: str
    owner_actor: str
    namespace: str
    status: str
    quotas: dict[str, Any]
    settings: dict[str, Any]


class MemberCreateRequest(BaseModel):
    actor: str
    org_role: str = Field(..., pattern="^(OWNER|ADMIN|MEMBER|VIEWER)$")
    rbac_role: str = Field(..., pattern="^(tenant_admin|admin|operator|viewer)$")


class MemberRoleUpdateRequest(BaseModel):
    org_role: str = Field(..., pattern="^(OWNER|ADMIN|MEMBER|VIEWER)$")
    rbac_role: str = Field(..., pattern="^(tenant_admin|admin|operator|viewer)$")


async def _require_org_member(session: AsyncSession, org_id: str, actor: str) -> None:
    row = (
        await session.execute(
            text("SELECT 1 FROM organization_members WHERE organization_id = :oid AND actor = :a"),
            {"oid": org_id, "a": actor},
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not an organization member",
        )


async def _require_org_manage(session: AsyncSession, org_id: str, actor: str) -> None:
    row = (
        await session.execute(
            text(
                """
                SELECT org_role FROM organization_members
                WHERE organization_id = :oid AND actor = :a
                """
            ),
            {"oid": org_id, "a": actor},
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not an organization member",
        )
    if str(row[0]) not in ("OWNER", "ADMIN"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="org:manage required")


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: CreateOrganizationRequest,
    actor: str = DEP_ACTOR,
    db: AsyncSession = DEP_DB,
) -> Organization:
    svc = OrganizationService(db)
    org = await svc.create_org(body.name, body.display_name, actor)
    return org


@router.get("/{org_id}", response_model=OrganizationResponse)
async def get_organization(
    org_id: str,
    actor: str = DEP_ACTOR,
    db: AsyncSession = DEP_DB,
) -> Organization:
    await _require_org_member(db, org_id, actor)
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return org


@router.put("/{org_id}", response_model=OrganizationResponse)
async def update_organization(
    org_id: str,
    body: UpdateOrganizationRequest,
    actor: str = DEP_ACTOR,
    db: AsyncSession = DEP_DB,
) -> Organization:
    await _require_org_manage(db, org_id, actor)
    org = await db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if body.display_name is not None:
        org.display_name = body.display_name
    if body.settings is not None:
        org.settings = body.settings
    await db.flush()
    return org


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: str,
    actor: str = DEP_ACTOR,
    db: AsyncSession = DEP_DB,
) -> Response:
    await _require_org_manage(db, org_id, actor)
    svc = OrganizationService(db)
    await svc.handle_org_deleting(org_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{org_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    org_id: str,
    body: MemberCreateRequest,
    actor: str = DEP_ACTOR,
    db: AsyncSession = DEP_DB,
) -> dict[str, str]:
    await _require_org_manage(db, org_id, actor)
    from ulid import ULID

    mid = str(ULID())
    await db.execute(
        text(
            """
            INSERT INTO organization_members
              (id, organization_id, actor, org_role, rbac_role, joined_at)
            VALUES (:id, :oid, :act, :orole, :rrole, NOW())
            ON CONFLICT (organization_id, actor) DO NOTHING
            """
        ),
        {
            "id": mid,
            "oid": org_id,
            "act": body.actor,
            "orole": body.org_role,
            "rrole": body.rbac_role,
        },
    )
    return {"id": mid}


@router.get("/{org_id}/members")
async def list_members(
    org_id: str,
    actor: str = DEP_ACTOR,
    db: AsyncSession = DEP_DB,
) -> list[dict[str, Any]]:
    await _require_org_member(db, org_id, actor)
    result = await db.execute(
        text(
            """
            SELECT id, actor, org_role, rbac_role, joined_at
            FROM organization_members WHERE organization_id = :oid
            """
        ),
        {"oid": org_id},
    )
    rows = result.mappings().all()
    return [dict(r) for r in rows]


@router.delete("/{org_id}/members/{member_actor}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: str,
    member_actor: str,
    actor: str = DEP_ACTOR,
    db: AsyncSession = DEP_DB,
) -> Response:
    await _require_org_manage(db, org_id, actor)
    await db.execute(
        text("DELETE FROM organization_members WHERE organization_id = :oid AND actor = :a"),
        {"oid": org_id, "a": member_actor},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{org_id}/members/{member_actor}/role")
async def update_member_role(
    org_id: str,
    member_actor: str,
    body: MemberRoleUpdateRequest,
    actor: str = DEP_ACTOR,
    db: AsyncSession = DEP_DB,
) -> dict[str, str]:
    await _require_org_manage(db, org_id, actor)
    await db.execute(
        text(
            """
            UPDATE organization_members
            SET org_role = :orole, rbac_role = :rrole
            WHERE organization_id = :oid AND actor = :a
            """
        ),
        {
            "oid": org_id,
            "a": member_actor,
            "orole": body.org_role,
            "rrole": body.rbac_role,
        },
    )
    return {"status": "ok"}
