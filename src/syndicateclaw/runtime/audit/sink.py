"""Audit sink protocol — append-only execution records."""

from __future__ import annotations

from typing import Protocol

from syndicateclaw.runtime.contracts.execution import ExecutionRecord


class AuditSink(Protocol):
    """Every execution must call append exactly once with a complete record."""

    def append(self, record: ExecutionRecord) -> None:
        """Persist or forward the record. Raising fails the execution (fail closed)."""


class InMemoryAuditSink:
    """Process-local sink for tests and adapters."""

    def __init__(self) -> None:
        self.records: list[ExecutionRecord] = []

    def append(self, record: ExecutionRecord) -> None:
        self.records.append(record)


class FailingAuditSink:
    """Test double — always raises (fail closed verification)."""

    def append(self, record: ExecutionRecord) -> None:
        msg = "simulated audit failure"
        raise RuntimeError(msg)
