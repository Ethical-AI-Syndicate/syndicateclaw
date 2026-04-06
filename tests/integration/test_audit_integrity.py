"""DB-backed tests for audit/integrity.py."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_integrity_verifier_full_check_empty_db(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from syndicateclaw.audit.integrity import IntegrityVerifier

    verifier = IntegrityVerifier(session_factory)
    result = await verifier.full_check(limit=10)
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_integrity_verifier_verify_decision_hashes_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from syndicateclaw.audit.integrity import IntegrityVerifier

    result = await IntegrityVerifier(session_factory).verify_decision_hashes(limit=10)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_integrity_verifier_verify_snapshot_hashes_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from syndicateclaw.audit.integrity import IntegrityVerifier

    result = await IntegrityVerifier(session_factory).verify_snapshot_hashes(limit=10)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_integrity_verifier_find_unlinked_executions_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from syndicateclaw.audit.integrity import IntegrityVerifier

    result = await IntegrityVerifier(session_factory).find_unlinked_tool_executions(limit=10)
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_integrity_verifier_detect_version_drift_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from syndicateclaw.audit.integrity import IntegrityVerifier

    result = await IntegrityVerifier(session_factory).detect_version_drift(limit=10)
    assert isinstance(result, list)
