from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import factory

from syndicateclaw.db.models import (
    ApiKey,
    ApprovalRequest,
    AuditEvent,
    PolicyRule,
    WorkflowDefinition,
    WorkflowRun,
)


class WorkflowDefinitionFactory(factory.Factory):
    class Meta:
        model = WorkflowDefinition

    id = factory.LazyFunction(lambda: str(uuid4()))
    name = factory.Sequence(lambda n: f"workflow-{n}")
    version = "1.0.0"
    description = "Factory workflow definition"
    nodes = factory.LazyFunction(dict)
    edges = factory.LazyFunction(dict)
    owner = "test-owner"
    metadata_ = factory.LazyFunction(dict)


class WorkflowRunFactory(factory.Factory):
    class Meta:
        model = WorkflowRun

    id = factory.LazyFunction(lambda: str(uuid4()))
    workflow = factory.SubFactory(WorkflowDefinitionFactory)
    workflow_id = factory.SelfAttribute("workflow.id")
    workflow_version = "1.0.0"
    status = "PENDING"
    state = factory.LazyFunction(dict)
    initiated_by = "test-actor"


class PolicyRuleFactory(factory.Factory):
    class Meta:
        model = PolicyRule

    id = factory.LazyFunction(lambda: str(uuid4()))
    name = factory.Sequence(lambda n: f"policy-rule-{n}")
    description = "Factory policy rule"
    resource_type = "tool"
    resource_pattern = "*"
    effect = "ALLOW"
    conditions = factory.LazyFunction(list)
    priority = 10
    enabled = True
    owner = "test-owner"


class AuditEventFactory(factory.Factory):
    class Meta:
        model = AuditEvent

    id = factory.LazyFunction(lambda: str(uuid4()))
    event_type = "WORKFLOW_CREATED"
    actor = "test-actor"
    resource_type = "workflow"
    resource_id = factory.LazyFunction(lambda: str(uuid4()))
    action = "create"
    details = factory.LazyFunction(dict)
    trace_id = factory.LazyFunction(lambda: str(uuid4()))
    span_id = factory.LazyFunction(lambda: str(uuid4()))


class ApprovalRequestFactory(factory.Factory):
    class Meta:
        model = ApprovalRequest

    id = factory.LazyFunction(lambda: str(uuid4()))
    run = factory.SubFactory(WorkflowRunFactory)
    run_id = factory.SelfAttribute("run.id")
    node_execution_id = factory.LazyFunction(lambda: str(uuid4()))
    tool_name = "test-tool"
    action_description = "Factory approval request"
    risk_level = "MEDIUM"
    status = "PENDING"
    requested_by = "test-actor"
    assigned_to = factory.LazyFunction(lambda: ["test-actor-admin"])
    expires_at = factory.LazyFunction(lambda: datetime.now(UTC) + timedelta(hours=1))
    context = factory.LazyFunction(dict)
    scope = factory.LazyFunction(dict)


class ApiKeyFactory(factory.Factory):
    class Meta:
        model = ApiKey

    id = factory.LazyFunction(lambda: str(uuid4()))
    key_hash = factory.LazyFunction(lambda: uuid4().hex)
    key_prefix = factory.LazyFunction(lambda: uuid4().hex[:8])
    actor = "test-actor"
    description = "Factory API key"
    revoked = False
