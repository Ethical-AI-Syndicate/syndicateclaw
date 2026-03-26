# QA test data seeder — runs in qa environment container
import os
import sys
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from syndicateclaw.db.models import (
    WorkflowDefinition, WorkflowRun, AuditEvent, MemoryRecord,
    ToolExecution, PolicyRule, ApprovalRequest, DecisionRecord
)
from syndicateclaw.db.base import engine, async_session

SEED_WORKFLOW = {
    "name": "qa-invoice-approval",
    "description": "Test workflow for QA: invoice approval with human review",
    "nodes": [
        {"id": "start", "type": "START", "handler": "start", "config": {}},
        {"id": "validate", "type": "ACTION", "handler": "validate_invoice", "config": {"timeout_seconds": 30}},
        {"id": "high_amount", "type": "DECISION", "handler": "decision", "config": {"condition": "state.invoice_amount > 5000"}},
        {"id": "auto_approve", "type": "ACTION", "handler": "auto_approve", "config": {}},
        {"id": "manual_review", "type": "APPROVAL", "handler": "approval", "config": {"assigned_to": ["qa-reviewer@aisYndicate.io"]}},
        {"id": "end", "type": "END", "handler": "end", "config": {}},
    ],
    "edges": [
        {"from_node_id": "start", "to_node_id": "validate"},
        {"from_node_id": "validate", "to_node_id": "high_amount"},
        {"from_node_id": "high_amount", "to_node_id": "manual_review", "condition": "true"},
        {"from_node_id": "high_amount", "to_node_id": "auto_approve", "condition": "false"},
        {"from_node_id": "auto_approve", "to_node_id": "end"},
        {"from_node_id": "manual_review", "to_node_id": "end"},
    ]
}

SEED_POLICY_RULES = [
    {"name": "qa-allow-all-tools", "resource_type": "tool", "resource_id": "*", "action": "*", "effect": "ALLOW", "priority": 100},
    {"name": "qa-deny-delete-All", "resource_type": "tool", "resource_id": "delete_all", "action": "execute", "effect": "DENY", "priority": 200},
]

async def seed():
    print("🌱 Seeding QA database...")
    
    from sqlalchemy.ext.asyncio import AsyncSession
    async with async_session() as session:
        # Seed workflow
        wf = WorkflowDefinition(
            owner="qa-test-user",
            name=SEED_WORKFLOW["name"],
            description=SEED_WORKFLOW["description"],
            definition=SEED_WORKFLOW
        )
        session.add(wf)
        await session.flush()
        print(f"  📋 Workflow created: {wf.name} (ID: {wf.id})")

        # Seed policy rules
        for rule_data in SEED_POLICY_RULES:
            rule = PolicyRule(**rule_data)
            session.add(rule)
            print(f"  📜 Policy rule: {rule.name}")

        await session.commit()
        print("✅ QA database seeded successfully")

if __name__ == "__main__":
    asyncio.run(seed())
