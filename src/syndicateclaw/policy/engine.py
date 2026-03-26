from __future__ import annotations

import re
from datetime import UTC, datetime
from fnmatch import fnmatch
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.audit.service import AuditService
from syndicateclaw.db.models import PolicyDecision as PolicyDecisionRow
from syndicateclaw.db.models import PolicyRule as PolicyRuleRow
from syndicateclaw.db.repository import PolicyDecisionRepository, PolicyRuleRepository
from syndicateclaw.models import (
    AuditEventType,
    PolicyCondition,
    PolicyDecision,
    PolicyEffect,
    PolicyRule,
)
from syndicateclaw.observability.metrics import record_policy_evaluation

logger = structlog.get_logger(__name__)

_DENY_RULE_ID = "__default_deny__"


class PolicyEngine:
    """Evaluates policy rules against resource actions using a fail-closed model."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._audit = AuditService(session_factory)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate(
        self,
        resource_type: str,
        resource_id: str,
        action: str,
        actor: str,
        context: dict[str, Any],
    ) -> PolicyDecision:
        """Evaluate all matching policy rules and return a decision.

        First matching rule (sorted by priority desc) wins.
        If nothing matches the default is DENY (fail-closed).
        Any exception in the evaluation path returns DENY (fail-closed).
        """
        decision: PolicyDecision | None = None
        try:
            async with self._session_factory() as session, session.begin():
                rule_repo = PolicyRuleRepository(session)
                decision_repo = PolicyDecisionRepository(session)

                rules = await rule_repo.get_enabled_by_resource_type(resource_type)

                matching_rules = [
                    r for r in rules if self._match_resource(r.resource_pattern, resource_id)
                ]

                for rule_row in matching_rules:
                    raw_conds: Any = rule_row.conditions
                    if raw_conds is None:
                        conditions_list: list[Any] = []
                    elif isinstance(raw_conds, list):
                        conditions_list = raw_conds
                    else:
                        conditions_list = []
                    condition_results: list[dict[str, Any]] = []
                    all_match = True

                    for cond_data in conditions_list:
                        if isinstance(cond_data, PolicyCondition):
                            cond = cond_data
                        elif isinstance(cond_data, dict):
                            cond = PolicyCondition(**cond_data)
                        else:
                            continue
                        result = self._evaluate_condition(cond, context)
                        condition_results.append({
                            "field": cond.field,
                            "operator": cond.operator,
                            "expected": cond.value,
                            "actual": _resolve_field(context, cond.field),
                            "matched": result,
                        })
                        if not result:
                            all_match = False
                            break

                    if all_match:
                        decision = PolicyDecision.new(
                            rule_id=rule_row.id,
                            rule_name=rule_row.name,
                            effect=PolicyEffect(rule_row.effect),
                            resource_type=resource_type,
                            resource_id=resource_id,
                            actor=actor,
                            reason=f"Matched rule '{rule_row.name}' (priority {rule_row.priority})",
                            conditions_evaluated=condition_results,
                        )
                        break

                if decision is None:
                    decision = PolicyDecision.new(
                        rule_id=_DENY_RULE_ID,
                        rule_name="default_deny",
                        effect=PolicyEffect.DENY,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        actor=actor,
                        reason="No matching policy rule found — default DENY",
                        conditions_evaluated=[],
                    )

                row = PolicyDecisionRow(
                    id=decision.id,
                    rule_id=decision.rule_id,
                    rule_name=decision.rule_name,
                    effect=decision.effect.value,
                    resource_type=decision.resource_type,
                    resource_id=decision.resource_id,
                    actor=decision.actor,
                    reason=decision.reason,
                    conditions_evaluated=decision.conditions_evaluated,
                    timestamp=decision.timestamp,
                )
                await decision_repo.create(row)

        except Exception as exc:
            logger.exception(
                "policy_engine.evaluate_failed",
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                actor=actor,
            )
            decision = PolicyDecision.new(
                rule_id="__evaluation_error__",
                rule_name="evaluation_error",
                effect=PolicyEffect.DENY,
                resource_type=resource_type,
                resource_id=resource_id,
                actor=actor,
                reason=f"Policy evaluation failed (fail-closed): {exc}",
                conditions_evaluated=[{"error": "evaluation_exception", "detail": str(exc)}],
            )
            try:
                await self._emit_audit(
                    AuditEventType.POLICY_DENIED,
                    actor,
                    {
                        "resource_type": resource_type,
                        "resource_id": resource_id,
                        "action": action,
                        "effect": PolicyEffect.DENY.value,
                        "rule_id": decision.rule_id,
                        "rule_name": decision.rule_name,
                        "reason": decision.reason,
                        "fail_closed": True,
                    },
                )
            except Exception:
                logger.exception("policy_engine.audit_emit_failed_after_eval_error")
            record_policy_evaluation("error")
            logger.info(
                "policy_evaluated",
                resource_type=resource_type,
                resource_id=resource_id,
                action=action,
                effect=decision.effect.value,
                rule=decision.rule_name,
                status="failure",
            )
            return decision

        await self._emit_audit(
            AuditEventType.POLICY_EVALUATED,
            actor,
            {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
                "effect": decision.effect.value,
                "rule_id": decision.rule_id,
                "rule_name": decision.rule_name,
                "reason": decision.reason,
            },
        )

        record_policy_evaluation(
            "allow" if decision.effect == PolicyEffect.ALLOW else "deny",
        )
        logger.info(
            "policy_evaluated",
            resource_type=resource_type,
            resource_id=resource_id,
            action=action,
            effect=decision.effect.value,
            rule=decision.rule_name,
            status="success",
        )
        return decision

    async def add_rule(self, rule: PolicyRule, actor: str) -> PolicyRule:
        """Persist a new policy rule."""
        async with self._session_factory() as session, session.begin():
            repo = PolicyRuleRepository(session)
            row = PolicyRuleRow(
                id=rule.id,
                name=rule.name,
                description=rule.description,
                resource_type=rule.resource_type,
                resource_pattern=rule.resource_pattern,
                effect=rule.effect.value,
                conditions=[c.model_dump() for c in rule.conditions],
                priority=rule.priority,
                enabled=rule.enabled,
                owner=rule.owner,
            )
            await repo.create(row)

        await self._emit_audit(
            AuditEventType.POLICY_CREATED,
            actor,
            {"rule_id": rule.id, "rule_name": rule.name},
        )
        return rule

    async def update_rule(
        self, rule_id: str, updates: dict[str, Any], actor: str
    ) -> PolicyRule:
        """Load, update, and persist a policy rule."""
        async with self._session_factory() as session, session.begin():
            repo = PolicyRuleRepository(session)
            row = await repo.get(rule_id)
            if row is None:
                raise ValueError(f"Policy rule {rule_id} not found")

            for key, value in updates.items():
                if key == "conditions":
                    value = [
                        c.model_dump() if isinstance(c, PolicyCondition) else c
                        for c in value
                    ]
                if key == "effect" and isinstance(value, PolicyEffect):
                    value = value.value
                if hasattr(row, key):
                    setattr(row, key, value)
            row.updated_at = datetime.now(UTC)
            row = await repo.update(row)
            result = PolicyRule.model_validate(row)

        await self._emit_audit(
            AuditEventType.POLICY_UPDATED,
            actor,
            {"rule_id": rule_id, "updates": list(updates.keys())},
        )
        return result

    async def delete_rule(self, rule_id: str, actor: str) -> None:
        """Soft-delete a policy rule by disabling it."""
        async with self._session_factory() as session, session.begin():
            repo = PolicyRuleRepository(session)
            row = await repo.get(rule_id)
            if row is None:
                raise ValueError(f"Policy rule {rule_id} not found")
            row.enabled = False
            row.updated_at = datetime.now(UTC)
            await repo.update(row)

        await self._emit_audit(
            AuditEventType.POLICY_DELETED,
            actor,
            {"rule_id": rule_id},
        )

    async def list_rules(
        self, resource_type: str | None = None
    ) -> list[PolicyRule]:
        """Return rules, optionally filtered by resource type."""
        async with self._session_factory() as session:
            repo = PolicyRuleRepository(session)
            if resource_type:
                rows = await repo.get_enabled_by_resource_type(resource_type)
            else:
                rows = await repo.list()
            return [PolicyRule.model_validate(r) for r in rows]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _evaluate_condition(
        self, condition: PolicyCondition, context: dict[str, Any]
    ) -> bool:
        """Safely evaluate a single policy condition against the context."""
        actual = _resolve_field(context, condition.field)
        expected = condition.value
        op = condition.operator

        try:
            if op == "eq":
                return bool(actual == expected)
            if op == "neq":
                return bool(actual != expected)
            if op == "in":
                return bool(actual in expected)
            if op == "not_in":
                return bool(actual not in expected)
            if op == "gt":
                return bool(actual > expected)
            if op == "lt":
                return bool(actual < expected)
            if op == "gte":
                return bool(actual >= expected)
            if op == "lte":
                return bool(actual <= expected)
            if op == "matches":
                return bool(re.search(str(expected), str(actual)))
        except (TypeError, ValueError):
            return False

        logger.warning("unknown_policy_operator", operator=op)
        return False

    def _match_resource(self, pattern: str, resource_id: str) -> bool:
        """Use fnmatch glob matching for resource patterns."""
        return fnmatch(resource_id, pattern)

    async def _emit_audit(
        self,
        event_type: AuditEventType,
        actor: str,
        details: dict[str, Any],
    ) -> None:
        event = AuditService.create_event(
            event_type=event_type,
            actor=actor,
            resource_type="policy_rule",
            resource_id=details.get("rule_id", ""),
            action=event_type.value,
            details=details,
        )
        await self._audit.emit(event)


def _resolve_field(context: dict[str, Any], field_path: str) -> Any:
    """Resolve a dot-separated field path from a nested dict."""
    parts = field_path.split(".")
    current: Any = context
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current
