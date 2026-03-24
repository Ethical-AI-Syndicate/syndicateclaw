"""Scheduled memory review workflow for expired record lifecycle management."""

from __future__ import annotations

from syndicateclaw.models import (
    EdgeDefinition,
    NodeDefinition,
    NodeType,
    WorkflowDefinition,
)


def build_scheduled_memory_review_workflow() -> WorkflowDefinition:
    nodes = [
        NodeDefinition(
            id="start",
            name="Start",
            node_type=NodeType.START,
            handler="start",
        ),
        NodeDefinition(
            id="scan_expired",
            name="Scan Expired Memories",
            node_type=NodeType.ACTION,
            handler="llm",
            config={
                "prompt": (
                    "Scan the memory store for records past their TTL or "
                    "expiration date. Set state.expired_count and "
                    "state.expired_ids."
                ),
                "model": "gpt-4o",
                "output_key": "expired_count",
            },
            timeout_seconds=60,
        ),
        NodeDefinition(
            id="has_expired",
            name="Has Expired Records?",
            node_type=NodeType.DECISION,
            handler="decision",
            config={
                "condition": "state.expired_count > 0",
                "true_node": "review_batch",
                "false_node": "skip_node",
            },
        ),
        NodeDefinition(
            id="review_batch",
            name="Review Expired Batch",
            node_type=NodeType.APPROVAL,
            handler="approval",
            config={
                "description": "Review the batch of expired memory records before purging.",
                "risk_level": "MEDIUM",
                "assigned_to": ["admin"],
                "expires_hours": 72,
            },
        ),
        NodeDefinition(
            id="purge",
            name="Purge Expired Records",
            node_type=NodeType.ACTION,
            handler="llm",
            config={
                "prompt": (
                    "Purge the approved expired memory records listed in "
                    "state.expired_ids from the memory store."
                ),
                "model": "gpt-4o",
                "output_key": "purge_result",
            },
            timeout_seconds=90,
        ),
        NodeDefinition(
            id="report",
            name="Generate Report",
            node_type=NodeType.ACTION,
            handler="llm",
            config={
                "prompt": (
                    "Generate a summary report of the purge operation "
                    "including counts and any errors. Store in state.report."
                ),
                "model": "gpt-4o",
                "output_key": "report",
            },
            timeout_seconds=30,
        ),
        NodeDefinition(
            id="skip_node",
            name="No Expired Records",
            node_type=NodeType.ACTION,
            handler="llm",
            config={
                "prompt": "No expired records found. Log a clean-scan result.",
                "model": "gpt-4o",
                "output_key": "scan_result",
            },
            timeout_seconds=10,
        ),
        NodeDefinition(
            id="end",
            name="End",
            node_type=NodeType.END,
            handler="end",
        ),
    ]

    edges = [
        EdgeDefinition(source_node_id="start", target_node_id="scan_expired"),
        EdgeDefinition(source_node_id="scan_expired", target_node_id="has_expired"),
        EdgeDefinition(
            source_node_id="has_expired",
            target_node_id="review_batch",
            condition="state.expired_count > 0",
            priority=1,
        ),
        EdgeDefinition(
            source_node_id="has_expired",
            target_node_id="skip_node",
            condition="state.expired_count == 0",
            priority=0,
        ),
        EdgeDefinition(source_node_id="review_batch", target_node_id="purge"),
        EdgeDefinition(source_node_id="purge", target_node_id="report"),
        EdgeDefinition(source_node_id="report", target_node_id="end"),
        EdgeDefinition(source_node_id="skip_node", target_node_id="end"),
    ]

    return WorkflowDefinition(
        name="scheduled-memory-review",
        version="1.0.0",
        description=(
            "Periodically scans the memory store for expired records. "
            "When expired records exist, an admin reviews and approves "
            "the batch before purging. A summary report is generated "
            "after each cycle."
        ),
        nodes=nodes,
        edges=edges,
        owner="platform-team",
        metadata={"domain": "memory-lifecycle", "schedule": "daily"},
    )


if __name__ == "__main__":
    workflow = build_scheduled_memory_review_workflow()
    print(workflow.model_dump_json(indent=2))
