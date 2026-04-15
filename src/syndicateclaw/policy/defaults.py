from syndicateclaw.models import PolicyDecision, PolicyEffect, PolicyRule
from syndicateclaw.policy.models import PolicyContext


class DefaultPolicy:
    RULE_ID = "__default_deny__"
    RULE_NAME = "default_deny"
    VERSION = "policy-v1"

    @classmethod
    def evaluate(cls, context: PolicyContext) -> PolicyDecision:
        return PolicyDecision.new(
            rule_id=cls.RULE_ID,
            rule_name=cls.RULE_NAME,
            effect=PolicyEffect.DENY,
            resource_type=context.resource_type,
            resource_id=context.resource_id,
            actor=context.actor,
            reason="No matching policy rule found — default DENY",
            conditions_evaluated=[],
            policy_version=cls.VERSION,
        )


class PolicyEvaluator:
    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self._rules: list[PolicyRule] = rules or []
        self._default_policy = DefaultPolicy()

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def evaluate(self, context: PolicyContext) -> PolicyDecision:
        try:
            for rule in self._rules:
                if not rule.enabled:
                    continue

                if not self._matches_resource(rule, context):
                    continue

                if not self._matches_conditions(rule, context):
                    continue

                return PolicyDecision.new(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    effect=rule.effect,
                    resource_type=context.resource_type,
                    resource_id=context.resource_id,
                    actor=context.actor,
                    reason=f"Matched rule '{rule.name}' (priority {rule.priority})",
                    conditions_evaluated=[],
                    policy_version="policy-v1",
                )

            return self._default_policy.evaluate(context)

        except Exception as e:
            return PolicyDecision.new(
                rule_id="__evaluation_error__",
                rule_name="evaluation_error",
                effect=PolicyEffect.DENY,
                resource_type=context.resource_type,
                resource_id=context.resource_id,
                actor=context.actor,
                reason=f"Policy evaluation failed (fail-closed): {e}",
                conditions_evaluated=[{"error": str(e)}],
                policy_version="policy-v1",
            )

    def _matches_resource(self, rule: PolicyRule, context: PolicyContext) -> bool:
        from fnmatch import fnmatch

        return fnmatch(context.resource_id, rule.resource_pattern)

    def _matches_conditions(self, rule: PolicyRule, context: PolicyContext) -> bool:
        for cond in rule.conditions:
            actual = context.get(cond.field)
            expected = cond.value

            op = cond.operator
            if op == "eq":
                if actual != expected:
                    return False
            elif op == "neq":
                if actual == expected:
                    return False
            elif op == "in":
                if actual not in expected:
                    return False
            elif op == "not_in":
                if actual in expected:
                    return False
            elif op == "gt":
                if not (actual > expected):
                    return False
            elif op == "lt":
                if not (actual < expected):
                    return False
            elif op == "gte":
                if not (actual >= expected):
                    return False
            elif op == "lte":
                if not (actual <= expected):
                    return False
            elif op == "matches":
                import re

                if not re.search(str(expected), str(actual)):
                    return False
            elif op == "contains":
                if expected not in actual:
                    return False

        return True
