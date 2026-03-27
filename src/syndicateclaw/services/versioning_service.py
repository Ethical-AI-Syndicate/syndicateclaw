from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import WorkflowDefinition, WorkflowVersion, WorkflowVersionArchive
from syndicateclaw.messaging.metrics import workflow_versions_total


class VersionNotFoundError(Exception):
    """Raised when a requested workflow version does not exist."""


class VersioningService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_version(
        self,
        workflow_id: str,
        definition: dict[str, Any],
        actor: str,
        comment: str | None = None,
    ) -> int:
        async with self._session_factory() as session, session.begin():
            wf = await session.get(WorkflowDefinition, workflow_id, with_for_update=True)
            if wf is None:
                raise VersionNotFoundError("workflow not found")

            next_version = int(wf.current_version) + 1
            row = WorkflowVersion(
                workflow_id=workflow_id,
                version=next_version,
                definition=definition,
                changed_by=actor,
                comment=comment,
            )
            session.add(row)

            wf.current_version = next_version
            wf.updated_by = actor
            wf.nodes = definition.get("nodes", wf.nodes)
            wf.edges = definition.get("edges", wf.edges)
            wf.metadata_ = definition.get("metadata", wf.metadata_)
            namespace = str(wf.metadata_.get("namespace", "default"))
            workflow_versions_total.labels(namespace=namespace).inc()
            await self._enforce_version_cap(session, workflow_id)
            return next_version

    async def _enforce_version_cap(
        self,
        session: AsyncSession,
        workflow_id: str,
        cap: int = 100,
    ) -> None:
        total = await session.execute(
            select(func.count())
            .select_from(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
        )
        count = int(total.scalar_one())
        if count <= cap:
            return

        overflow = count - cap
        oldest = await session.execute(
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version.asc())
            .limit(overflow)
        )
        rows = list(oldest.scalars().all())
        for row in rows:
            session.add(
                WorkflowVersionArchive(
                    workflow_id=row.workflow_id,
                    version=row.version,
                    definition=row.definition,
                    changed_by=row.changed_by,
                    changed_at=row.changed_at,
                    comment=row.comment,
                )
            )
            await session.delete(row)

    async def list_versions(
        self,
        workflow_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[WorkflowVersion]:
        stmt: Select[tuple[WorkflowVersion]] = (
            select(WorkflowVersion)
            .where(WorkflowVersion.workflow_id == workflow_id)
            .order_by(WorkflowVersion.version.desc())
            .offset(offset)
            .limit(limit)
        )
        async with self._session_factory() as session:
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_version(self, workflow_id: str, version: int) -> WorkflowVersion:
        async with self._session_factory() as session:
            result = await session.execute(
                select(WorkflowVersion).where(
                    WorkflowVersion.workflow_id == workflow_id,
                    WorkflowVersion.version == version,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                raise VersionNotFoundError("version not found")
            return row

    async def rollback(
        self,
        workflow_id: str,
        target_version: int,
        actor: str,
        comment: str | None = None,
    ) -> int:
        target = await self.get_version(workflow_id, target_version)
        reason = comment or f"Rollback to version {target_version}"
        return await self.create_version(workflow_id, target.definition, actor, reason)

    async def diff(self, workflow_id: str, from_version: int, to_version: int) -> dict[str, Any]:
        v_from = await self.get_version(workflow_id, from_version)
        v_to = await self.get_version(workflow_id, to_version)

        from_nodes = {str(n.get("id")): n for n in v_from.definition.get("nodes", [])}
        to_nodes = {str(n.get("id")): n for n in v_to.definition.get("nodes", [])}
        from_edges = {
            str(e.get("id", f"{e.get('source_node_id')}->{e.get('target_node_id')}")): e
            for e in v_from.definition.get("edges", [])
        }
        to_edges = {
            str(e.get("id", f"{e.get('source_node_id')}->{e.get('target_node_id')}")): e
            for e in v_to.definition.get("edges", [])
        }

        nodes_added = sorted(set(to_nodes) - set(from_nodes))
        nodes_removed = sorted(set(from_nodes) - set(to_nodes))
        nodes_changed = sorted(
            [k for k in set(from_nodes) & set(to_nodes) if from_nodes[k] != to_nodes[k]]
        )
        edges_added = sorted(set(to_edges) - set(from_edges))
        edges_removed = sorted(set(from_edges) - set(to_edges))

        return {
            "from_version": from_version,
            "to_version": to_version,
            "nodes_added": nodes_added,
            "nodes_removed": nodes_removed,
            "nodes_changed": nodes_changed,
            "edges_added": edges_added,
            "edges_removed": edges_removed,
            "metadata_changed": {
                "from": v_from.definition.get("metadata", {}),
                "to": v_to.definition.get("metadata", {}),
            },
        }
