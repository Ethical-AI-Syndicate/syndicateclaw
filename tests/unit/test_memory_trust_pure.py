"""Pure unit tests for MemoryTrustService scoring (no database)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from syndicateclaw.memory.trust import MemoryTrustService


def test_compute_effective_trust_frozen_unchanged() -> None:
    svc = MemoryTrustService(MagicMock())
    assert svc.compute_effective_trust(0.42, 0.1, datetime.now(UTC), frozen=True) == 0.42


def test_compute_effective_trust_no_validation_timestamp() -> None:
    svc = MemoryTrustService(MagicMock())
    assert svc.compute_effective_trust(0.9, 0.5, None, frozen=False) == 0.9


def test_compute_effective_trust_decay_clamped() -> None:
    svc = MemoryTrustService(MagicMock())
    old = datetime.now(UTC) - timedelta(days=10)
    eff = svc.compute_effective_trust(1.0, 0.2, old, frozen=False)
    assert 0.0 <= eff <= 1.0


def test_is_usable_respects_threshold() -> None:
    svc = MemoryTrustService(MagicMock(), min_usable_trust=0.5)
    assert svc.is_usable(0.51) is True
    assert svc.is_usable(0.49) is False
