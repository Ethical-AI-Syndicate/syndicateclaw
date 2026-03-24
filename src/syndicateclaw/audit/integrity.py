from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from syndicateclaw.db.models import (
    AuditEvent as DBAuditEvent,
    DecisionRecord as DBDecisionRecord,
    InputSnapshot as DBInputSnapshot,
    ToolExecution as DBToolExecution,
    WorkflowRun as DBWorkflowRun,
)

logger = structlog.get_logger(__name__)


class IntegrityVerifier:
    """Scheduled integrity verification for the decision ledger,
    input snapshots, and audit completeness.

    Run periodically to detect:
    - Tampered decision records (hash mismatch)
    - Missing ledger links on tool executions
    - Corrupted input snapshots
    - Tool executions without decision records
    - Policy/tool/version drift between runs
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def verify_decision_hashes(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Re-hash decision record inputs and report any mismatches."""
        violations: list[dict[str, Any]] = []

        async with self._session_factory() as session:
            stmt = select(DBDecisionRecord).order_by(
                DBDecisionRecord.created_at.desc()
            ).limit(limit)
            result = await session.execute(stmt)
            records = list(result.scalars().all())

        for rec in records:
            inputs = rec.inputs or {}
            expected = hashlib.sha256(
                json.dumps(inputs, sort_keys=True, default=str).encode()
            ).hexdigest()
            if expected != (rec.context_hash or ""):
                violations.append({
                    "decision_record_id": rec.id,
                    "expected_hash": expected,
                    "stored_hash": rec.context_hash,
                    "domain": rec.domain,
                    "created_at": rec.created_at.isoformat() if rec.created_at else None,
                })

        logger.info(
            "integrity.decision_hashes_verified",
            checked=len(records),
            violations=len(violations),
        )
        return violations

    async def verify_snapshot_hashes(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Re-hash snapshot response data and report mismatches."""
        violations: list[dict[str, Any]] = []

        async with self._session_factory() as session:
            stmt = select(DBInputSnapshot).order_by(
                DBInputSnapshot.created_at.desc()
            ).limit(limit)
            result = await session.execute(stmt)
            snapshots = list(result.scalars().all())

        for snap in snapshots:
            response_data = snap.response_data or {}
            expected = hashlib.sha256(
                json.dumps(response_data, sort_keys=True, default=str).encode()
            ).hexdigest()
            if expected != (snap.content_hash or ""):
                violations.append({
                    "snapshot_id": snap.id,
                    "run_id": snap.run_id,
                    "expected_hash": expected,
                    "stored_hash": snap.content_hash,
                    "snapshot_type": snap.snapshot_type,
                })

        logger.info(
            "integrity.snapshot_hashes_verified",
            checked=len(snapshots),
            violations=len(violations),
        )
        return violations

    async def find_unlinked_tool_executions(self, limit: int = 1000) -> list[dict[str, Any]]:
        """Find tool executions that have no corresponding decision record."""
        orphans: list[dict[str, Any]] = []

        async with self._session_factory() as session:
            stmt = select(DBToolExecution).where(
                DBToolExecution.policy_decision_id.is_(None),
                DBToolExecution.status == "COMPLETED",
            ).order_by(
                DBToolExecution.created_at.desc()
            ).limit(limit)
            result = await session.execute(stmt)
            executions = list(result.scalars().all())

        for ex in executions:
            orphans.append({
                "tool_execution_id": ex.id,
                "tool_name": ex.tool_name,
                "run_id": ex.run_id,
                "created_at": ex.created_at.isoformat() if ex.created_at else None,
            })

        logger.info(
            "integrity.unlinked_tool_executions",
            found=len(orphans),
        )
        return orphans

    async def detect_version_drift(self, limit: int = 100) -> list[dict[str, Any]]:
        """Compare version manifests across recent runs to detect drift."""
        async with self._session_factory() as session:
            stmt = select(DBWorkflowRun).where(
                DBWorkflowRun.version_manifest.is_not(None),
            ).order_by(
                DBWorkflowRun.created_at.desc()
            ).limit(limit)
            result = await session.execute(stmt)
            runs = list(result.scalars().all())

        if len(runs) < 2:
            return []

        drift_reports: list[dict[str, Any]] = []
        baseline = runs[0].version_manifest or {}

        for run in runs[1:]:
            manifest = run.version_manifest or {}
            diffs: dict[str, Any] = {}

            for key in set(list(baseline.keys()) + list(manifest.keys())):
                if baseline.get(key) != manifest.get(key):
                    diffs[key] = {
                        "baseline": baseline.get(key),
                        "this_run": manifest.get(key),
                    }

            if diffs:
                drift_reports.append({
                    "baseline_run_id": runs[0].id,
                    "compared_run_id": run.id,
                    "differences": diffs,
                })

        logger.info(
            "integrity.version_drift_check",
            runs_compared=len(runs),
            drift_detected=len(drift_reports),
        )
        return drift_reports

    async def full_check(self, limit: int = 1000) -> dict[str, Any]:
        """Run all integrity checks and return a combined report."""
        decision_violations = await self.verify_decision_hashes(limit)
        snapshot_violations = await self.verify_snapshot_hashes(limit)
        unlinked = await self.find_unlinked_tool_executions(limit)
        drift = await self.detect_version_drift(min(limit, 100))

        report = {
            "checked_at": datetime.now(UTC).isoformat(),
            "decision_hash_violations": len(decision_violations),
            "snapshot_hash_violations": len(snapshot_violations),
            "unlinked_tool_executions": len(unlinked),
            "version_drift_instances": len(drift),
            "healthy": (
                len(decision_violations) == 0
                and len(snapshot_violations) == 0
                and len(unlinked) == 0
            ),
            "details": {
                "decision_violations": decision_violations[:10],
                "snapshot_violations": snapshot_violations[:10],
                "unlinked_executions": unlinked[:10],
                "drift_reports": drift[:10],
            },
        }

        logger.info(
            "integrity.full_check_complete",
            healthy=report["healthy"],
            violations=report["decision_hash_violations"] + report["snapshot_hash_violations"],
        )
        return report
