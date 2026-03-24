"""Outbound communication workflow with mandatory approval gate."""

from __future__ import annotations

from syndicateclaw.models import (
    EdgeDefinition,
    NodeDefinition,
    NodeType,
    WorkflowDefinition,
)


def build_outbound_comms_workflow() -> WorkflowDefinition:
    nodes = [
        NodeDefinition(
            id="start",
            name="Start",
            node_type=NodeType.START,
            handler="start",
        ),
        NodeDefinition(
            id="draft_message",
            name="Draft Message",
            node_type=NodeType.ACTION,
            handler="llm",
            config={
                "prompt": (
                    "Draft an outbound message based on the communication "
                    "brief in state.brief. Store the draft in state.draft."
                ),
                "model": "gpt-4o",
                "output_key": "draft",
            },
            timeout_seconds=45,
        ),
        NodeDefinition(
            id="review_approval",
            name="Comms Review Approval",
            node_type=NodeType.APPROVAL,
            handler="approval",
            config={
                "description": "Review the drafted outbound message before it is sent.",
                "risk_level": "HIGH",
                "assigned_to": ["comms-team"],
                "expires_hours": 24,
            },
        ),
        NodeDefinition(
            id="checkpoint",
            name="Checkpoint",
            node_type=NodeType.CHECKPOINT,
            handler="checkpoint",
        ),
        NodeDefinition(
            id="send_message",
            name="Send Message",
            node_type=NodeType.ACTION,
            handler="llm",
            config={
                "prompt": (
                    "Send the approved message via the configured delivery "
                    "channel. Record the delivery receipt in state.delivery_receipt."
                ),
                "model": "gpt-4o",
                "output_key": "delivery_receipt",
            },
            timeout_seconds=30,
        ),
        NodeDefinition(
            id="end",
            name="End",
            node_type=NodeType.END,
            handler="end",
        ),
    ]

    edges = [
        EdgeDefinition(source_node_id="start", target_node_id="draft_message"),
        EdgeDefinition(source_node_id="draft_message", target_node_id="review_approval"),
        EdgeDefinition(source_node_id="review_approval", target_node_id="checkpoint"),
        EdgeDefinition(source_node_id="checkpoint", target_node_id="send_message"),
        EdgeDefinition(source_node_id="send_message", target_node_id="end"),
    ]

    return WorkflowDefinition(
        name="outbound-comms",
        version="1.0.0",
        description=(
            "Drafts and sends outbound communications. Every message requires "
            "comms-team approval before delivery to prevent unauthorised external "
            "communications."
        ),
        nodes=nodes,
        edges=edges,
        owner="comms-team",
        metadata={"domain": "communications", "requires_approval": True},
    )


if __name__ == "__main__":
    workflow = build_outbound_comms_workflow()
    print(workflow.model_dump_json(indent=2))
