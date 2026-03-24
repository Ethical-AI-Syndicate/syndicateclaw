from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from syndicateclaw.api.dependencies import (
    get_current_actor,
    get_db_session,
    get_policy_engine,
)
from syndicateclaw.models import PolicyCondition, PolicyEffect

logger = structlog.get_logger(__name__)

POLICY_ADMIN_PREFIXES = ("admin:", "policy:", "system:")


def _require_policy_admin(actor: str) -> None:
    """Enforce RBAC: only policy administrators can manage rules."""
    if not any(actor.startswith(prefix) for prefix in POLICY_ADMIN_PREFIXES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Actor '{actor}' lacks policy management permissions. Required role prefix: {POLICY_ADMIN_PREFIXES}",
        )


router = APIRouter(prefix="/api/v1/policies", tags=["policies"])

# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class CreatePolicyRuleRequest(BaseModel):
    name: str
    description: str = ""
    resource_type: str
    resource_pattern: str
    effect: PolicyEffect
    conditions: list[PolicyCondition] = Field(default_factory=list)
    priority: int = 0


class UpdatePolicyRuleRequest(BaseModel):
    description: str | None = None
    resource_pattern: str | None = None
    effect: PolicyEffect | None = None
    conditions: list[PolicyCondition] | None = None
    priority: int | None = None
    enabled: bool | None = None


class PolicyRuleResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    description: str | None = None
    resource_type: str
    resource_pattern: str
    effect: str
    conditions: list[dict[str, Any]] | Any
    priority: int
    enabled: bool
    owner: str | None = None
    created_at: datetime
    updated_at: datetime


class EvaluatePolicyRequest(BaseModel):
    resource_type: str
    resource_id: str
    action: str = "execute"
    actor: str
    context: dict[str, Any] = Field(default_factory=dict)


class PolicyDecisionResponse(BaseModel):
    effect: PolicyEffect
    rule_name: str | None = None
    reason: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/", response_model=PolicyRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_policy_rule(
    body: CreatePolicyRuleRequest,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    _require_policy_admin(actor)
    from syndicateclaw.db.models import PolicyRule as PRModel

    rule = PRModel(
        name=body.name,
        description=body.description,
        resource_type=body.resource_type,
        resource_pattern=body.resource_pattern,
        effect=body.effect.value,
        conditions=[c.model_dump() for c in body.conditions],
        priority=body.priority,
        owner=actor,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    logger.info("policy.created", rule_id=rule.id, name=body.name)
    return rule


@router.get("/", response_model=list[PolicyRuleResponse])
async def list_policy_rules(
    resource_type: str | None = Query(None),
    enabled: bool | None = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    from sqlalchemy import select

    from syndicateclaw.db.models import PolicyRule as PRModel

    stmt = select(PRModel)
    if resource_type:
        stmt = stmt.where(PRModel.resource_type == resource_type)
    if enabled is not None:
        stmt = stmt.where(PRModel.enabled == enabled)
    stmt = stmt.order_by(PRModel.priority.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{rule_id}", response_model=PolicyRuleResponse)
async def get_policy_rule(
    rule_id: str,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    from syndicateclaw.db.models import PolicyRule as PRModel

    rule = await db.get(PRModel, rule_id)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Policy rule not found"
        )
    return rule


@router.put("/{rule_id}", response_model=PolicyRuleResponse)
async def update_policy_rule(
    rule_id: str,
    body: UpdatePolicyRuleRequest,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    _require_policy_admin(actor)
    from syndicateclaw.db.models import PolicyRule as PRModel

    rule = await db.get(PRModel, rule_id)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Policy rule not found"
        )

    if body.description is not None:
        rule.description = body.description
    if body.resource_pattern is not None:
        rule.resource_pattern = body.resource_pattern
    if body.effect is not None:
        rule.effect = body.effect.value
    if body.conditions is not None:
        rule.conditions = [c.model_dump() for c in body.conditions]
    if body.priority is not None:
        rule.priority = body.priority
    if body.enabled is not None:
        rule.enabled = body.enabled

    await db.flush()
    await db.refresh(rule)
    logger.info("policy.updated", rule_id=rule_id)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy_rule(
    rule_id: str,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
):
    _require_policy_admin(actor)
    from syndicateclaw.db.models import PolicyRule as PRModel

    rule = await db.get(PRModel, rule_id)
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Policy rule not found"
        )
    rule.enabled = False
    await db.flush()
    logger.info("policy.disabled", rule_id=rule_id)


@router.post("/evaluate", response_model=PolicyDecisionResponse)
async def evaluate_policy(
    body: EvaluatePolicyRequest,
    actor: str = Depends(get_current_actor),
    db=Depends(get_db_session),
    policy_engine=Depends(get_policy_engine),
):
    if hasattr(policy_engine, "evaluate"):
        decision = await policy_engine.evaluate(
            body.resource_type, body.resource_id, body.action, body.actor, body.context
        )
        return decision

    from sqlalchemy import select

    from syndicateclaw.db.models import PolicyRule as PRModel

    stmt = (
        select(PRModel)
        .where(
            PRModel.resource_type == body.resource_type,
            PRModel.enabled.is_(True),
        )
        .order_by(PRModel.priority.desc())
    )
    result = await db.execute(stmt)
    rules = list(result.scalars().all())

    import fnmatch

    for rule in rules:
        if fnmatch.fnmatch(body.resource_id, rule.resource_pattern):
            return PolicyDecisionResponse(
                effect=PolicyEffect(rule.effect),
                rule_name=rule.name,
                reason=f"Matched rule: {rule.name}",
            )

    return PolicyDecisionResponse(
        effect=PolicyEffect.DENY,
        rule_name=None,
        reason="No matching policy rule — default DENY (fail-closed)",
    )
