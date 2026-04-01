"""Incident triage workflow with severity-based routing and approval gates."""

from __future__ import annotations

from syndicateclaw.models import (
    EdgeDefinition,
    NodeDefinition,
    NodeType,
    RetryPolicy,
    WorkflowDefinition,
)


def build_incident_triage_workflow() -> WorkflowDefinition:
    nodes = [
        NodeDefinition(
            id="start",
            name="Start",
            node_type=NodeType.START,
            handler="start",
        ),
        NodeDefinition(
            id="classify_incident",
            name="Classify Incident",
            node_type=NodeType.ACTION,
            handler="llm",
            config={
                "prompt": (
                    "Analyse the incoming incident report and classify its severity "
                    "as 'critical', 'high', 'medium', or 'low'. "
                    "Set state.severity to the result."
                ),
                "model": "gpt-4o",
                "output_key": "severity",
            },
            timeout_seconds=30,
        ),
        NodeDefinition(
            id="check_severity",
            name="Check Severity",
            node_type=NodeType.DECISION,
            handler="decision",
            config={
                "condition": "state.severity == 'critical'",
                "true_node": "request_approval",
                "false_node": "auto_remediate",
            },
        ),
        NodeDefinition(
            id="request_approval",
            name="Request Ops Approval",
            node_type=NodeType.APPROVAL,
            handler="approval",
            config={
                "description": (
                    "Critical incident detected — approve remediation plan before execution."
                ),
                "risk_level": "HIGH",
                "assigned_to": ["ops-team"],
                "expires_hours": 4,
            },
        ),
        NodeDefinition(
            id="checkpoint_state",
            name="Checkpoint State",
            node_type=NodeType.CHECKPOINT,
            handler="checkpoint",
        ),
        NodeDefinition(
            id="execute_remediation",
            name="Execute Remediation",
            node_type=NodeType.ACTION,
            handler="llm",
            config={
                "prompt": (
                    "Given the approved remediation plan in state, execute the "
                    "necessary steps to resolve the critical incident."
                ),
                "model": "gpt-4o",
                "output_key": "remediation_result",
            },
            retry_policy=RetryPolicy(
                max_attempts=2,
                backoff_seconds=5.0,
                backoff_multiplier=2.0,
                retryable_errors=["TimeoutError", "TransientError"],
            ),
            timeout_seconds=120,
        ),
        NodeDefinition(
            id="auto_remediate",
            name="Auto Remediate",
            node_type=NodeType.ACTION,
            handler="llm",
            config={
                "prompt": (
                    "Apply standard auto-remediation playbook for a "
                    "non-critical incident based on the classification in state."
                ),
                "model": "gpt-4o",
                "output_key": "remediation_result",
            },
            timeout_seconds=60,
        ),
        NodeDefinition(
            id="end",
            name="End",
            node_type=NodeType.END,
            handler="end",
        ),
    ]

    edges = [
        EdgeDefinition(source_node_id="start", target_node_id="classify_incident"),
        EdgeDefinition(source_node_id="classify_incident", target_node_id="check_severity"),
        EdgeDefinition(
            source_node_id="check_severity",
            target_node_id="request_approval",
            condition="state.severity == 'critical'",
            priority=1,
        ),
        EdgeDefinition(
            source_node_id="check_severity",
            target_node_id="auto_remediate",
            condition="state.severity != 'critical'",
            priority=0,
        ),
        EdgeDefinition(source_node_id="request_approval", target_node_id="checkpoint_state"),
        EdgeDefinition(source_node_id="checkpoint_state", target_node_id="execute_remediation"),
        EdgeDefinition(source_node_id="execute_remediation", target_node_id="end"),
        EdgeDefinition(source_node_id="auto_remediate", target_node_id="end"),
    ]

    return WorkflowDefinition(
        name="incident-triage",
        version="1.0.0",
        description=(
            "Triages incoming incidents by severity. Critical incidents require "
            "ops-team approval before remediation; lower-severity incidents are "
            "remediated automatically."
        ),
        nodes=nodes,
        edges=edges,
        owner="platform-team",
        metadata={"domain": "incident-response", "sla_minutes": 30},
    )


if __name__ == "__main__":
    workflow = build_incident_triage_workflow()
    print(workflow.model_dump_json(indent=2))
