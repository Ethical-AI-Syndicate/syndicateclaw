from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from .service import MemoryService

logger = structlog.get_logger(__name__)


@dataclass
class RetentionReport:
    """Summary produced after a retention enforcement run."""

    expired_count: int = 0
    deleted_count: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_purged(self) -> int:
        return self.expired_count + self.deleted_count


class RetentionEnforcer:
    """Periodic task that enforces memory retention policies by purging
    expired and soft-deleted records."""

    def __init__(self, memory_service: MemoryService) -> None:
        self._memory_service = memory_service

    async def run(self) -> RetentionReport:
        """Execute one retention sweep and return a report."""
        report = RetentionReport()

        try:
            purged = await self._memory_service.enforce_retention()
            report.expired_count = purged
        except Exception as exc:
            report.errors.append(f"Retention enforcement failed: {exc}")
            logger.error(
                "retention.enforcement_failed",
                error=str(exc),
                exc_info=True,
            )

        logger.info(
            "retention.run_complete",
            expired_count=report.expired_count,
            deleted_count=report.deleted_count,
            error_count=len(report.errors),
        )
        return report
