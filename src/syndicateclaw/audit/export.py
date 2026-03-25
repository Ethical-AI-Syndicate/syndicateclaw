from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import (
    ApprovalRequest as DBApprovalRequest,
)
from syndicateclaw.db.models import (
    AuditEvent as DBAuditEvent,
)
from syndicateclaw.db.models import (
    DecisionRecord as DBDecisionRecord,
)
from syndicateclaw.db.models import (
    InputSnapshot as DBInputSnapshot,
)
from syndicateclaw.db.models import (
    NodeExecution as DBNodeExecution,
)
from syndicateclaw.db.models import (
    ToolExecution as DBToolExecution,
)
from syndicateclaw.db.models import (
    WorkflowRun as DBWorkflowRun,
)

logger = structlog.get_logger(__name__)


class RunExporter:
    """Exports a complete, self-contained evidence bundle for a workflow run.

    The bundle contains everything needed for incident review, audit,
    or litigation:
    - Run metadata and version manifest
    - All node executions
    - All tool executions with decision record links
    - All decision records
    - All input snapshots
    - All approval requests and decisions
    - All audit events
    - Integrity hashes for tamper detection

    The bundle itself is hashed for chain-of-custody.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        signing_key: bytes | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._signing_key = signing_key

    async def export_run(self, run_id: str) -> dict[str, Any]:
        """Export a complete evidence bundle for a workflow run."""
        async with self._session_factory() as session:
            run = await session.get(DBWorkflowRun, run_id)
            if run is None:
                raise ValueError(f"Run {run_id} not found")

            nodes_stmt = select(DBNodeExecution).where(
                DBNodeExecution.run_id == run_id
            ).order_by(DBNodeExecution.created_at.asc())
            nodes = list((await session.execute(nodes_stmt)).scalars().all())

            tools_stmt = select(DBToolExecution).where(
                DBToolExecution.run_id == run_id
            ).order_by(DBToolExecution.created_at.asc())
            tools = list((await session.execute(tools_stmt)).scalars().all())

            decisions_stmt = select(DBDecisionRecord).where(
                DBDecisionRecord.run_id == run_id
            ).order_by(DBDecisionRecord.created_at.asc())
            decisions = list((await session.execute(decisions_stmt)).scalars().all())

            snapshots_stmt = select(DBInputSnapshot).where(
                DBInputSnapshot.run_id == run_id
            ).order_by(DBInputSnapshot.captured_at.asc())
            snapshots = list((await session.execute(snapshots_stmt)).scalars().all())

            approvals_stmt = select(DBApprovalRequest).where(
                DBApprovalRequest.run_id == run_id
            ).order_by(DBApprovalRequest.created_at.asc())
            approvals = list((await session.execute(approvals_stmt)).scalars().all())

            audit_stmt = select(DBAuditEvent).where(
                DBAuditEvent.resource_id == run_id
            ).order_by(DBAuditEvent.created_at.asc())
            audit_events = list((await session.execute(audit_stmt)).scalars().all())

        def _serialize_row(row: Any) -> dict[str, Any]:
            data: dict[str, Any] = {}
            for col in row.__table__.columns:
                val = getattr(row, col.name, None)
                if isinstance(val, datetime):
                    val = val.isoformat()
                elif isinstance(val, bytes):
                    val = val.hex()
                data[col.name] = val
            return data

        bundle: dict[str, Any] = {
            "export_version": "1.0.0",
            "exported_at": datetime.now(UTC).isoformat(),
            "run": _serialize_row(run),
            "version_manifest": run.version_manifest,
            "node_executions": [_serialize_row(n) for n in nodes],
            "tool_executions": [_serialize_row(t) for t in tools],
            "decision_records": [_serialize_row(d) for d in decisions],
            "input_snapshots": [_serialize_row(s) for s in snapshots],
            "approval_requests": [_serialize_row(a) for a in approvals],
            "audit_events": [_serialize_row(e) for e in audit_events],
            "counts": {
                "node_executions": len(nodes),
                "tool_executions": len(tools),
                "decision_records": len(decisions),
                "input_snapshots": len(snapshots),
                "approval_requests": len(approvals),
                "audit_events": len(audit_events),
            },
        }

        canonical = json.dumps(bundle, sort_keys=True, default=str)
        bundle["bundle_hash"] = hashlib.sha256(canonical.encode()).hexdigest()

        if self._signing_key:
            from syndicateclaw.security.signing import sign_payload
            bundle["bundle_hmac"] = sign_payload(bundle, self._signing_key)

        logger.info(
            "export.run_bundle_created",
            run_id=run_id,
            node_count=len(nodes),
            tool_count=len(tools),
            decision_count=len(decisions),
            snapshot_count=len(snapshots),
            signed=self._signing_key is not None,
        )
        return bundle
