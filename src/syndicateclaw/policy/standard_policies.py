from syndicateclaw.models import PolicyCondition, PolicyEffect, PolicyRule
from typing import ClassVar


class MTLSRequiredPolicy(PolicyRule):
    def __init__(self) -> None:
        super().__init__(
            id="__mtls_required__",
            name="mTLS Required",
            description="Requires mTLS identity for all access",
            resource_type="*",
            resource_pattern="*",
            effect=PolicyEffect.DENY,
            conditions=[
                PolicyCondition(
                    field="context.mtls_identity",
                    operator="neq",
                    value=None,
                ),
            ],
            priority=1000,
            enabled=True,
        )


class TenantBindingPolicy(PolicyRule):
    def __init__(self) -> None:
        super().__init__(
            id="__tenant_binding__",
            name="Tenant Binding Required",
            description="Requires valid tenant binding",
            resource_type="*",
            resource_pattern="*",
            effect=PolicyEffect.DENY,
            conditions=[
                PolicyCondition(
                    field="context.tenant_id",
                    operator="neq",
                    value=None,
                ),
            ],
            priority=900,
            enabled=True,
        )


class RedisQuotaPolicy(PolicyRule):
    def __init__(
        self,
        quota: int = 100,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(
            id="__redis_quota__",
            name=f"Rate Limit: {quota}/{window_seconds}s",
            description=f"Enforces {quota} requests per {window_seconds} seconds",
            resource_type="*",
            resource_pattern="*",
            effect=PolicyEffect.DENY,
            conditions=[
                PolicyCondition(
                    field="context.rate_limit_remaining",
                    operator="lt",
                    value=1,
                ),
            ],
            priority=800,
            enabled=True,
        )


class HighRiskToolPolicy(PolicyRule):
    HIGH_RISK_TOOLS: ClassVar[set[str]] = {
        "shell",
        "exec",
        "sql_query",
        "file_write",
        "network_request",
    }

    def __init__(self) -> None:
        super().__init__(
            id="__high_risk_tool__",
            name="High-Risk Tool Approval Required",
            description="Requires approval for high-risk tool execution",
            resource_type="tool",
            resource_pattern="*",
            effect=PolicyEffect.REQUIRE_APPROVAL,
            conditions=[
                PolicyCondition(
                    field="context.tools",
                    operator="contains",
                    value="shell",
                ),
            ],
            priority=700,
            enabled=True,
        )


def get_standard_policies() -> list[type[PolicyRule]]:
    return [
        MTLSRequiredPolicy,
        TenantBindingPolicy,
        RedisQuotaPolicy,
        HighRiskToolPolicy,
    ]


def create_standard_policy(policy_class: type[PolicyRule]) -> PolicyRule:
    return policy_class()
