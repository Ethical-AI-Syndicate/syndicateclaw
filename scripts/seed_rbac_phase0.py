#!/usr/bin/env python3
"""Phase 0 RBAC seed script.

Populates principals, built-in roles, role assignments, principal ID
back-references, and owning scope columns for all existing data.

Idempotent — safe to run multiple times. Existing rows are skipped.

Usage:
    SYNDICATECLAW_DATABASE_URL=postgresql+asyncpg://... python scripts/seed_rbac_phase0.py
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from ulid import ULID

DATABASE_URL = os.environ.get(
    "SYNDICATECLAW_DATABASE_URL",
    "postgresql+asyncpg://syndicateclaw:syndicateclaw@localhost:5432/syndicateclaw",
)

SEED_ACTOR = "system:seed"

BUILT_IN_ROLES: list[dict] = [
    {
        "name": "viewer",
        "description": "Read-only access to resources within scope.",
        "inherits_from": None,
        "permissions": [
            "workflow:read",
            "run:read",
            "memory:read",
            "audit:read",
            "tool:read",
            "policy:read",
            "approval:read",
        ],
    },
    {
        "name": "operator",
        "description": "Can create and execute workflows, write memory, request approvals.",
        "inherits_from": "viewer",
        "permissions": [
            "workflow:create",
            "workflow:execute",
            "run:create",
            "run:control",
            "run:replay",
            "memory:write",
            "tool:execute",
            "approval:request",
        ],
    },
    {
        "name": "admin",
        "description": "Full management within scope including policy and tools.",
        "inherits_from": "operator",
        "permissions": [
            "workflow:delete",
            "memory:delete",
            "tool:manage",
            "policy:manage",
            "policy:evaluate",
            "approval:decide",
            "namespace:read",
            "namespace:bind",
        ],
    },
    {
        "name": "tenant_admin",
        "description": (
            "Tenant-wide administration including audit export and principal management."
        ),
        "inherits_from": "admin",
        "permissions": [
            "audit:export",
            "system:manage_keys",
            "system:manage_principals",
        ],
    },
    {
        "name": "platform_admin",
        "description": "Full platform access including system configuration and impersonation.",
        "inherits_from": "tenant_admin",
        "permissions": [
            "system:configure",
            "system:impersonate",
        ],
    },
]

CUSTOM_ROLES: list[dict] = [
    {
        "name": "policy_manager",
        "description": "Transitional role for actors with policy:* prefix conventions.",
        "permissions": ["policy:read", "policy:evaluate", "policy:manage"],
    },
]


def _ulid() -> str:
    return str(ULID())


def _now() -> datetime:
    return datetime.now(UTC)


async def _extract_actors(session: AsyncSession) -> set[str]:
    """Step 1: Extract all distinct actor strings from existing tables."""
    query = text("""
        SELECT DISTINCT actor_name FROM (
            SELECT owner AS actor_name FROM workflow_definitions WHERE owner IS NOT NULL
            UNION
            SELECT initiated_by FROM workflow_runs WHERE initiated_by IS NOT NULL
            UNION
            SELECT actor FROM memory_records WHERE actor IS NOT NULL
            UNION
            SELECT actor FROM api_keys
            UNION
            SELECT actor FROM audit_events
        ) AS actors
    """)
    result = await session.execute(query)
    return {row[0] for row in result.fetchall()}


async def _create_principals(
    session: AsyncSession,
    actors: set[str],
    dry_run: bool = False,
) -> tuple[dict[str, str], int]:
    """Step 2: Create a principal for each actor. Returns name→id mapping and created count."""
    existing = await session.execute(text("SELECT name, id FROM principals"))
    name_to_id = {row[0]: row[1] for row in existing.fetchall()}

    created_count = 0
    for actor in sorted(actors):
        if actor in name_to_id:
            continue
        principal_type = "SERVICE_ACCOUNT" if actor.startswith("system:") else "USER"
        pid = _ulid()
        now = _now()
        if not dry_run:
            await session.execute(
                text("""
                    INSERT INTO principals
                        (id, principal_type, name, enabled, created_at, updated_at)
                    VALUES (:id, :ptype, :name, true, :now, :now)
                    ON CONFLICT (principal_type, name) DO NOTHING
                """),
                {"id": pid, "ptype": principal_type, "name": actor, "now": now},
            )
        name_to_id[actor] = pid
        created_count += 1

    return name_to_id, created_count


async def _create_roles(session: AsyncSession, dry_run: bool = False) -> tuple[dict[str, str], int]:
    """Step 3: Create built-in and custom roles. Returns name→id mapping and created count."""
    existing = await session.execute(text("SELECT name, id FROM roles"))
    name_to_id = {row[0]: row[1] for row in existing.fetchall()}

    created_count = 0
    for role_def in BUILT_IN_ROLES:
        if role_def["name"] in name_to_id:
            continue
        rid = _ulid()
        now = _now()
        if not dry_run:
            await session.execute(
                text("""
                    INSERT INTO roles (id, name, description, built_in, permissions,
                                       inherits_from, scope_type, created_by,
                                       created_at, updated_at)
                    VALUES (:id, :name, :desc, true, CAST(:perms AS jsonb),
                            :inherits, 'PLATFORM', :created_by, :now, :now)
                    ON CONFLICT (name, scope_type) DO NOTHING
                """),
                {
                    "id": rid,
                    "name": role_def["name"],
                    "desc": role_def["description"],
                    "perms": _json_list(role_def["permissions"]),
                    "inherits": role_def["inherits_from"],
                    "created_by": SEED_ACTOR,
                    "now": now,
                },
            )
        name_to_id[role_def["name"]] = rid
        created_count += 1

    for role_def in CUSTOM_ROLES:
        if role_def["name"] in name_to_id:
            continue
        rid = _ulid()
        now = _now()
        if not dry_run:
            await session.execute(
                text("""
                    INSERT INTO roles (id, name, description, built_in, permissions,
                                       scope_type, created_by, created_at, updated_at)
                    VALUES (:id, :name, :desc, false, CAST(:perms AS jsonb),
                            'PLATFORM', :created_by, :now, :now)
                    ON CONFLICT (name, scope_type) DO NOTHING
                """),
                {
                    "id": rid,
                    "name": role_def["name"],
                    "desc": role_def["description"],
                    "perms": _json_list(role_def["permissions"]),
                    "created_by": SEED_ACTOR,
                    "now": now,
                },
            )
        name_to_id[role_def["name"]] = rid
        created_count += 1

    return name_to_id, created_count


def _json_list(items: list[str]) -> str:
    import json

    return json.dumps(items)


def _classify_actor(actor: str) -> tuple[str, bool]:
    """Returns (role_name, transitional) for the given actor string."""
    if actor.startswith("admin:"):
        return "admin", False
    if actor.startswith("policy:"):
        return "policy_manager", False
    if actor == "system:engine" or actor == "system:scheduler":
        return "operator", False
    if actor.startswith("system:"):
        return "viewer", False
    return "operator", True


async def _create_assignments(
    session: AsyncSession,
    actors: set[str],
    principal_map: dict[str, str],
    role_map: dict[str, str],
    dry_run: bool = False,
) -> int:
    """Step 4: Create role assignments mirroring current conventions. Returns created count."""
    existing = await session.execute(text("SELECT principal_id, role_id FROM role_assignments"))
    existing_pairs = {(row[0], row[1]) for row in existing.fetchall()}

    created_count = 0
    for actor in sorted(actors):
        pid = principal_map.get(actor)
        if pid is None:
            continue
        role_name, transitional = _classify_actor(actor)
        rid = role_map.get(role_name)
        if rid is None:
            print(f"WARNING: role '{role_name}' not found for actor '{actor}'", file=sys.stderr)
            continue
        if (pid, rid) in existing_pairs:
            continue
        now = _now()
        if not dry_run:
            await session.execute(
                text("""
                    INSERT INTO role_assignments
                        (id, principal_id, role_id, scope_type, scope_id,
                         granted_by, granted_at, transitional, revoked, created_at, updated_at)
                    VALUES (:id, :pid, :rid, 'PLATFORM', 'platform',
                            :granted_by, :now, :transitional, false, :now, :now)
                """),
                {
                    "id": _ulid(),
                    "pid": pid,
                    "rid": rid,
                    "granted_by": SEED_ACTOR,
                    "now": now,
                    "transitional": transitional,
                },
            )
        created_count += 1
    return created_count


async def _populate_principal_ids(
    session: AsyncSession,
    principal_map: dict[str, str],
    dry_run: bool = False,
) -> int:
    """Step 5: Backfill principal ID columns on existing tables. Returns updated count."""
    updates = [
        ("workflow_definitions", "owner", "owner_principal_id"),
        ("workflow_runs", "initiated_by", "initiated_by_principal_id"),
        ("memory_records", "actor", "actor_principal_id"),
        ("audit_events", "actor", "actor_principal_id"),
        ("api_keys", "actor", "actor_principal_id"),
    ]
    total_updated = 0
    for table, actor_col, pid_col in updates:
        if dry_run:
            result = await session.execute(
                text(f"""
                    SELECT COUNT(*) FROM {table} t
                     INNER JOIN principals p ON p.name = t.{actor_col}
                     WHERE t.{pid_col} IS NULL
                """)
            )
            total_updated += result.scalar() or 0
        else:
            result = await session.execute(
                text(f"""
                    UPDATE {table} t
                       SET {pid_col} = p.id
                      FROM principals p
                     WHERE p.name = t.{actor_col}
                       AND t.{pid_col} IS NULL
                """)
            )
            total_updated += result.rowcount
    return total_updated


async def _populate_owning_scopes(session: AsyncSession, dry_run: bool = False) -> int:
    """Step 6: Set all existing resources to platform scope. Returns updated count."""
    tables = [
        "workflow_definitions",
        "workflow_runs",
        "memory_records",
        "approval_requests",
        "policy_rules",
    ]
    total_updated = 0
    for table in tables:
        if dry_run:
            result = await session.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE owning_scope_type IS NULL")
            )
            total_updated += result.scalar() or 0
        else:
            result = await session.execute(
                text(f"""
                    UPDATE {table}
                       SET owning_scope_type = 'PLATFORM',
                           owning_scope_id = 'platform'
                     WHERE owning_scope_type IS NULL
                """)
            )
            total_updated += result.rowcount
    return total_updated


async def _verify(session: AsyncSession) -> list[str]:
    """Run all invariant checks. Returns list of failures."""
    failures: list[str] = []

    # S1: Every actor has a principal
    result = await session.execute(
        text("""
        SELECT COUNT(*) FROM (
            SELECT owner AS a FROM workflow_definitions WHERE owner IS NOT NULL
            UNION
            SELECT initiated_by FROM workflow_runs WHERE initiated_by IS NOT NULL
            UNION
            SELECT actor FROM memory_records WHERE actor IS NOT NULL
            UNION
            SELECT actor FROM api_keys
            UNION
            SELECT actor FROM audit_events
        ) AS actors
        LEFT JOIN principals p ON p.name = actors.a
        WHERE p.id IS NULL
    """)
    )
    count = result.scalar()
    if count != 0:
        failures.append(f"S1 FAILED: {count} actors without principals")

    # S2: Exactly 6 roles
    result = await session.execute(text("SELECT COUNT(*) FROM roles"))
    count = result.scalar()
    if count != 6:
        failures.append(f"S2 FAILED: expected 6 roles, found {count}")

    # S3: 5 built-in roles
    result = await session.execute(text("SELECT COUNT(*) FROM roles WHERE built_in = true"))
    count = result.scalar()
    if count != 5:
        failures.append(f"S3 FAILED: expected 5 built-in roles, found {count}")

    # S4: Every principal has at least one assignment
    result = await session.execute(
        text("""
        SELECT COUNT(*) FROM principals p
        LEFT JOIN role_assignments ra ON ra.principal_id = p.id
        WHERE ra.id IS NULL
    """)
    )
    count = result.scalar()
    if count != 0:
        failures.append(f"S4 FAILED: {count} principals without assignments")

    # S7: No NULL principal IDs where actor string exists
    for table, actor_col, pid_col in [
        ("workflow_definitions", "owner", "owner_principal_id"),
        ("workflow_runs", "initiated_by", "initiated_by_principal_id"),
        ("memory_records", "actor", "actor_principal_id"),
        ("audit_events", "actor", "actor_principal_id"),
        ("api_keys", "actor", "actor_principal_id"),
    ]:
        result = await session.execute(
            text(f"""
            SELECT COUNT(*) FROM {table}
            WHERE {actor_col} IS NOT NULL AND {pid_col} IS NULL
        """)
        )
        count = result.scalar()
        if count != 0:
            failures.append(
                f"S7 FAILED: {table}.{pid_col} has {count} NULLs with non-NULL {actor_col}"
            )

    # S8: No NULL owning scopes
    for table in [
        "workflow_definitions",
        "workflow_runs",
        "memory_records",
        "approval_requests",
        "policy_rules",
    ]:
        result = await session.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE owning_scope_type IS NULL")
        )
        count = result.scalar()
        if count != 0:
            failures.append(f"S8 FAILED: {table} has {count} rows with NULL owning_scope_type")

    # S-service: All system:* actors are SERVICE_ACCOUNT
    result = await session.execute(
        text("""
        SELECT COUNT(*) FROM principals
        WHERE name LIKE 'system:%%' AND principal_type != 'SERVICE_ACCOUNT'
    """)
    )
    count = result.scalar()
    if count != 0:
        failures.append(f"SERVICE_ACCOUNT check FAILED: {count} system: actors misclassified")

    return failures


async def main(dry_run: bool = False, verify_only: bool = False) -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    if verify_only:
        async with session_factory() as session, session.begin():
            failures = await _verify(session)
        await engine.dispose()
        if failures:
            print(f"\nVERIFICATION FAILED — {len(failures)} invariant(s) broken:")
            for f in failures:
                print(f"  ✗ {f}")
            sys.exit(1)
        else:
            print("All invariants passed.")
            sys.exit(0)
        return

    async with session_factory() as session:
        async with session.begin():
            print("Step 1: Extracting distinct actors...")
            actors = await _extract_actors(session)
            print(f"  Found {len(actors)} distinct actors")

            print(f"Step 2: {'Planning' if dry_run else 'Creating'} principals...")
            principal_map, p_count = await _create_principals(session, actors, dry_run)
            print(f"  {p_count} principals {'planned' if dry_run else 'created'}")

            print(f"Step 3: {'Planning' if dry_run else 'Creating'} roles...")
            role_map, r_count = await _create_roles(session, dry_run)
            print(f"  {r_count} roles {'planned' if dry_run else 'created'}")

            print(f"Step 4: {'Planning' if dry_run else 'Creating'} role assignments...")
            ra_count = await _create_assignments(session, actors, principal_map, role_map, dry_run)
            print(f"  {ra_count} assignments {'planned' if dry_run else 'created'}")

            print(f"Step 5: {'Planning' if dry_run else 'Populating'} principal ID columns...")
            pid_count = await _populate_principal_ids(session, principal_map, dry_run)
            print(f"  {pid_count} columns {'to be updated' if dry_run else 'updated'}")

            print(f"Step 6: {'Planning' if dry_run else 'Populating'} owning scope columns...")
            os_count = await _populate_owning_scopes(session, dry_run)
            print(f"  {os_count} rows {'to be updated' if dry_run else 'updated'}")

        if not dry_run:
            print("\nRunning verification checks...")
            async with session.begin():
                failures = await _verify(session)
        else:
            failures = []

    await engine.dispose()

    if failures:
        print(f"\n{'=' * 60}")
        print(f"VERIFICATION FAILED — {len(failures)} invariant(s) broken:")
        for f in failures:
            print(f"  ✗ {f}")
        print(f"{'=' * 60}")
        sys.exit(1)
    elif not dry_run:
        print("\nAll invariants passed. Phase 0 seed complete.")
        sys.exit(0)
    else:
        print("\nDry run complete. No changes made.")
        sys.exit(0)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 0 RBAC seed script. Idempotent — safe to run multiple times."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without committing any changes.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run invariant checks only. Exit 0 if all pass, exit 1 if any fail. "
             "Does not seed any data.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(dry_run=args.dry_run, verify_only=args.verify))
