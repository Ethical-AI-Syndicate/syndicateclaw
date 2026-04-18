"""
Shadow RBAC gate test.

After seed_rbac_phase0.py runs, the PRINCIPAL_NOT_FOUND disagreement rate
must be 0%. This test fails loudly if principals are missing.

This is not a coverage test — it is a deployment readiness gate.
If this test fails, run: python scripts/seed_rbac_phase0.py
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker


@pytest.mark.asyncio
async def test_principal_not_found_rate_is_zero(db_engine):
    """
    Gate: after RBAC seeding, no PRINCIPAL_NOT_FOUND disagreements should exist
    in shadow_evaluations. A non-zero rate means enforcement is blocking real traffic.
    """
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as db_session:
        result = await db_session.execute(
            text(
                "SELECT COUNT(*) FROM shadow_evaluations "
                "WHERE disagreement_type = 'PRINCIPAL_NOT_FOUND'"
            )
        )
        pnf_count = result.scalar() or 0

        result = await db_session.execute(text("SELECT COUNT(*) FROM shadow_evaluations"))
        total = result.scalar() or 0

    if total > 0 and pnf_count > 0:
        rate = pnf_count / total
        pytest.fail(
            f"PRINCIPAL_NOT_FOUND disagreement rate is {rate:.1%} "
            f"({pnf_count}/{total} evaluations).\n"
            "RBAC enforcement is ON. Every missing principal causes a 403.\n"
            "Fix: run python scripts/seed_rbac_phase0.py against this database."
        )


@pytest.mark.asyncio
async def test_principals_table_not_empty(db_engine):
    """
    Gate: principals table must have at least one row after seeding.
    An empty principals table with enforcement ON blocks all requests.
    """
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as db_session:
        result = await db_session.execute(text("SELECT COUNT(*) FROM principals"))
        count = result.scalar() or 0
    assert count > 0, "principals table is empty. Run: python scripts/seed_rbac_phase0.py"


@pytest.mark.asyncio
async def test_system_actors_have_service_account_type(db_engine):
    """
    Gate: all system: principals must be SERVICE_ACCOUNT type.
    Misclassification causes role assignment mismatches.
    """
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as db_session:
        result = await db_session.execute(
            text(
                "SELECT COUNT(*) FROM principals "
                "WHERE name LIKE 'system:%' AND principal_type != 'SERVICE_ACCOUNT'"
            )
        )
        count = result.scalar() or 0
    assert count == 0, (
        f"{count} system: principals have wrong principal_type. "
        "Run: python scripts/seed_rbac_phase0.py"
    )
