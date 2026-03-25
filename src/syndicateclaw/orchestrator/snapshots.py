from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import InputSnapshot as InputSnapshotRow
from syndicateclaw.db.repository import InputSnapshotRepository
from syndicateclaw.models import InputSnapshot

logger = structlog.get_logger(__name__)


def _hash_response(data: dict[str, Any]) -> str:
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class InputSnapshotStore:
    """Captures and serves external input snapshots for replay.

    During LIVE mode: captures tool responses, memory reads, API responses.
    During DETERMINISTIC mode: serves frozen snapshots instead of making live calls.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def capture(
        self,
        *,
        run_id: str,
        node_execution_id: str,
        snapshot_type: str,
        source_identifier: str,
        request_data: dict[str, Any],
        response_data: dict[str, Any],
    ) -> InputSnapshot:
        """Capture an external input during live execution."""
        content_hash = _hash_response(response_data)

        snapshot = InputSnapshot.new(
            run_id=run_id,
            node_execution_id=node_execution_id,
            snapshot_type=snapshot_type,
            source_identifier=source_identifier,
            request_data=request_data,
            response_data=response_data,
            content_hash=content_hash,
            captured_at=datetime.now(UTC),
        )

        async with self._session_factory() as session, session.begin():
            repo = InputSnapshotRepository(session)
            row = InputSnapshotRow(
                id=snapshot.id,
                run_id=snapshot.run_id,
                node_execution_id=snapshot.node_execution_id,
                snapshot_type=snapshot.snapshot_type,
                source_identifier=snapshot.source_identifier,
                request_data=snapshot.request_data,
                response_data=snapshot.response_data,
                content_hash=snapshot.content_hash,
                captured_at=snapshot.captured_at,
            )
            await repo.create(row)

        logger.debug(
            "snapshot.captured",
            run_id=run_id,
            snapshot_type=snapshot_type,
            source=source_identifier,
        )
        return snapshot

    async def get_frozen(
        self,
        *,
        original_run_id: str,
        source_identifier: str,
    ) -> dict[str, Any] | None:
        """Retrieve a frozen response for deterministic replay.
        Returns None if no snapshot exists (caller must fall back to live).
        """
        async with self._session_factory() as session:
            repo = InputSnapshotRepository(session)
            snap = await repo.get_for_replay(original_run_id, source_identifier)
            if snap is None:
                return None
            return snap.response_data

    async def get_run_snapshots(self, run_id: str) -> list[InputSnapshot]:
        """Get all snapshots for a run, ordered chronologically."""
        async with self._session_factory() as session:
            repo = InputSnapshotRepository(session)
            rows = await repo.get_by_run(run_id)
            return [InputSnapshot.model_validate(r) for r in rows]

    async def verify_snapshot_integrity(self, snapshot_id: str) -> bool:
        """Re-hash response data and compare to stored hash."""
        async with self._session_factory() as session:
            row = await session.get(InputSnapshotRow, snapshot_id)
            if row is None:
                return False
            expected = _hash_response(row.response_data or {})
            return expected == row.content_hash

    async def detect_replay_divergence(
        self,
        *,
        run_id: str,
        source_identifier: str,
        live_response: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Compare a live response to the frozen snapshot.
        Returns a divergence report if they differ, None if identical.
        """
        frozen = await self.get_frozen(
            original_run_id=run_id,
            source_identifier=source_identifier,
        )
        if frozen is None:
            return None

        live_hash = _hash_response(live_response)
        frozen_hash = _hash_response(frozen)

        if live_hash == frozen_hash:
            return None

        return {
            "source_identifier": source_identifier,
            "run_id": run_id,
            "frozen_hash": frozen_hash,
            "live_hash": live_hash,
            "frozen_response_keys": list(frozen.keys()),
            "live_response_keys": list(live_response.keys()),
            "detected_at": datetime.now(UTC).isoformat(),
        }
