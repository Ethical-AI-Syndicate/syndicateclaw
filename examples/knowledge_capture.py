"""Knowledge capture workflow with confidence validation and provenance loop."""

from __future__ import annotations

from syndicateclaw.models import (
    EdgeDefinition,
    NodeDefinition,
    NodeType,
    RetryPolicy,
    WorkflowDefinition,
)


def build_knowledge_capture_workflow() -> WorkflowDefinition:
    nodes = [
        NodeDefinition(
            id="start",
            name="Start",
            node_type=NodeType.START,
            handler="start",
        ),
        NodeDefinition(
            id="extract_knowledge",
            name="Extract Knowledge",
            node_type=NodeType.ACTION,
            handler="llm",
            config={
                "prompt": (
                    "Extract structured knowledge from the source material. "
                    "Produce a confidence score (0-1) in state.confidence and "
                    "the extracted facts in state.knowledge."
                ),
                "model": "gpt-4o",
                "output_key": "knowledge",
            },
            retry_policy=RetryPolicy(
                max_attempts=3,
                backoff_seconds=2.0,
                backoff_multiplier=2.0,
                retryable_errors=["TimeoutError", "RateLimitError"],
            ),
            timeout_seconds=60,
        ),
        NodeDefinition(
            id="validate_confidence",
            name="Validate Confidence",
            node_type=NodeType.DECISION,
            handler="decision",
            config={
                "condition": "state.confidence > 0.7",
                "true_node": "checkpoint",
                "false_node": "request_review",
            },
        ),
        NodeDefinition(
            id="checkpoint",
            name="Checkpoint",
            node_type=NodeType.CHECKPOINT,
            handler="checkpoint",
        ),
        NodeDefinition(
            id="store_memory",
            name="Store Memory",
            node_type=NodeType.ACTION,
            handler="llm",
            config={
                "prompt": (
                    "Persist the validated knowledge into the memory store "
                    "with full provenance metadata."
                ),
                "model": "gpt-4o",
                "output_key": "memory_id",
            },
            timeout_seconds=30,
        ),
        NodeDefinition(
            id="request_review",
            name="Request Human Review",
            node_type=NodeType.APPROVAL,
            handler="approval",
            config={
                "description": (
                    "Extracted knowledge has low confidence — review and "
                    "provide corrections before re-extraction."
                ),
                "risk_level": "MEDIUM",
                "assigned_to": ["knowledge-team"],
                "expires_hours": 48,
            },
        ),
        NodeDefinition(
            id="re_extract",
            name="Re-Extract Knowledge",
            node_type=NodeType.ACTION,
            handler="llm",
            config={
                "prompt": (
                    "Re-extract knowledge incorporating reviewer feedback "
                    "from state.review_notes. Update state.confidence and "
                    "state.knowledge."
                ),
                "model": "gpt-4o",
                "output_key": "knowledge",
            },
            retry_policy=RetryPolicy(
                max_attempts=3,
                backoff_seconds=2.0,
                backoff_multiplier=2.0,
                retryable_errors=["TimeoutError", "RateLimitError"],
            ),
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
        EdgeDefinition(source_node_id="start", target_node_id="extract_knowledge"),
        EdgeDefinition(source_node_id="extract_knowledge", target_node_id="validate_confidence"),
        EdgeDefinition(
            source_node_id="validate_confidence",
            target_node_id="checkpoint",
            condition="state.confidence > 0.7",
            priority=1,
        ),
        EdgeDefinition(
            source_node_id="validate_confidence",
            target_node_id="request_review",
            condition="state.confidence <= 0.7",
            priority=0,
        ),
        EdgeDefinition(source_node_id="checkpoint", target_node_id="store_memory"),
        EdgeDefinition(source_node_id="store_memory", target_node_id="end"),
        EdgeDefinition(source_node_id="request_review", target_node_id="re_extract"),
        EdgeDefinition(source_node_id="re_extract", target_node_id="validate_confidence"),
    ]

    return WorkflowDefinition(
        name="knowledge-capture",
        version="1.0.0",
        description=(
            "Extracts structured knowledge from source material with confidence "
            "validation. Low-confidence extractions loop through human review "
            "before storage, ensuring provenance and quality."
        ),
        nodes=nodes,
        edges=edges,
        owner="knowledge-team",
        metadata={"domain": "knowledge-management", "supports_loop": True},
    )


if __name__ == "__main__":
    workflow = build_knowledge_capture_workflow()
    print(workflow.model_dump_json(indent=2))
