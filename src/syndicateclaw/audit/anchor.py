import json
import os
import io
import asyncio
from datetime import datetime, UTC
from typing import Any, Dict

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import AuditEvent as DBAuditEvent
from syndicateclaw.security.signing import SigningKeyPair

logger = structlog.get_logger(__name__)

class AnchorManifest:
    def __init__(self, schema_version: str, sequence_number: int, anchor_key: str, 
                 head_hash: str, signed_at: datetime, key_id: str, 
                 signature: str = "", previous_manifest_key: str = ""):
        self.schema_version = schema_version
        self.sequence_number = sequence_number
        self.anchor_key = anchor_key
        self.previous_manifest_key = previous_manifest_key
        self.head_hash = head_hash
        self.signed_at = signed_at
        self.key_id = key_id
        self.signature = signature

    def payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "sequence_number": self.sequence_number,
            "anchor_key": self.anchor_key,
            "previous_manifest_key": self.previous_manifest_key,
            "head_hash": self.head_hash,
            "signed_at": self.signed_at.isoformat().replace("+00:00", "Z"),
            "key_id": self.key_id
        }

class ChainAnchor:
    def __init__(self, schema_version: str, tenant_id: str, environment: str, 
                 sequence_number: int, head_hash: str, signed_at: datetime, 
                 key_id: str, signature: str = ""):
        self.schema_version = schema_version
        self.tenant_id = tenant_id
        self.environment = environment
        self.sequence_number = sequence_number
        self.head_hash = head_hash
        self.signed_at = signed_at
        self.key_id = key_id
        self.signature = signature

    def payload(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "environment": self.environment,
            "sequence_number": self.sequence_number,
            "head_hash": self.head_hash,
            "signed_at": self.signed_at.isoformat().replace("+00:00", "Z"),
            "key_id": self.key_id
        }


class ComplianceFileExporter:
    """Simulates S3 Object Lock Compliance Mode."""
    def __init__(self, root_path: str):
        self.root_path = root_path
        os.makedirs(os.path.join(root_path, "anchors"), exist_ok=True)
        os.makedirs(os.path.join(root_path, "manifests"), exist_ok=True)

    def export(self, anchor: ChainAnchor, manifest: AnchorManifest) -> None:
        now = datetime.now(UTC)
        date_path = f"{now.year}/{now.month:02d}/{now.day:02d}"
        
        anchor_filename = f"seq-{anchor.sequence_number:012d}.json"
        anchor_key = os.path.join("anchors", anchor.tenant_id, date_path, anchor_filename)
        anchor_path = os.path.join(self.root_path, anchor_key)

        manifest_filename = f"manifest-{manifest.sequence_number:012d}.json"
        manifest_key = os.path.join("manifests", anchor.tenant_id, date_path, manifest_filename)
        manifest_path = os.path.join(self.root_path, manifest_key)

        os.makedirs(os.path.dirname(anchor_path), exist_ok=True)
        os.makedirs(os.path.dirname(manifest_path), exist_ok=True)

        self._write_immutable(anchor_path, {**anchor.payload(), "signature": anchor.signature})
        
        manifest.anchor_key = anchor_key
        self._write_immutable(manifest_path, {**manifest.payload(), "anchor_key": anchor_key, "signature": manifest.signature})

        last_path = os.path.join(self.root_path, "manifests", anchor.tenant_id, "last_manifest.ptr")
        os.makedirs(os.path.dirname(last_path), exist_ok=True)
        with open(last_path, "w") as f:
            f.write(manifest_key)

    def get_last_manifest_key(self, tenant_id: str) -> str:
        last_path = os.path.join(self.root_path, "manifests", tenant_id, "last_manifest.ptr")
        if os.path.exists(last_path):
            with open(last_path, "r") as f:
                return f.read().strip()
        return ""

    def _write_immutable(self, path: str, data: dict) -> None:
        if os.path.exists(path):
            raise RuntimeError(f"WORM violation: object already exists at {path}")
        # Note: in Python os.O_EXCL provides atomic creation safety
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)

class AnchorService:
    """Exports anchors and full audit chains to simulate Canonical Export Compatibility."""
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        exporter: ComplianceFileExporter,
        signer: SigningKeyPair,
        key_id: str = "default",
        tenant_id: str = "default"
    ):
        self._session_factory = session_factory
        self._exporter = exporter
        self._signer = signer
        self._key_id = key_id
        self._tenant_id = tenant_id

    async def export_anchor(self) -> ChainAnchor:
        async with self._session_factory() as session:
            stmt = select(DBAuditEvent).where(DBAuditEvent.integrity_chain == "auth").order_by(DBAuditEvent.sequence_number.desc()).limit(1)
            res = await session.execute(stmt)
            latest = res.scalar_one_or_none()
            if not latest:
                raise ValueError("No events to anchor")
            
            anchor = ChainAnchor(
                schema_version="anchor-v1",
                tenant_id=self._tenant_id,
                environment="production",
                sequence_number=latest.sequence_number,
                head_hash=latest.event_hash,
                signed_at=datetime.now(UTC),
                key_id=self._key_id
            )
            anchor.signature = self._signer.sign(anchor.payload())

            last_manifest_key = self._exporter.get_last_manifest_key(self._tenant_id)
            manifest = AnchorManifest(
                schema_version="manifest-v1",
                sequence_number=latest.sequence_number,
                anchor_key="", # Set in export
                previous_manifest_key=last_manifest_key,
                head_hash=latest.event_hash,
                signed_at=anchor.signed_at,
                key_id=self._key_id
            )
            manifest.signature = self._signer.sign(manifest.payload())

            self._exporter.export(anchor, manifest)
            logger.info("anchor.exported", sequence_number=anchor.sequence_number, head_hash=anchor.head_hash)
            return anchor

    async def export_chain(self, output_path: str) -> None:
        """Exports the full chain in the format expected by `audit-verify`."""
        async with self._session_factory() as session:
            stmt = select(DBAuditEvent).where(DBAuditEvent.integrity_chain == "auth").order_by(DBAuditEvent.sequence_number.asc())
            res = await session.execute(stmt)
            events = res.scalars().all()
            
            out = []
            for e in events:
                out.append({
                    "SequenceNumber": e.sequence_number,
                    "EventID": e.id,
                    "EventHash": e.event_hash,
                    "PreviousHash": e.previous_hash,
                    "EventType": e.event_type,
                    "ActorID": e.actor,
                    "Payload": json.dumps(e.details) if isinstance(e.details, dict) else e.details,
                    "IntegrityChain": e.integrity_chain,
                    "LastAuthID": "",
                    "KeyID": e.key_id,
                    "Signature": e.signature,
                    "CreatedAt": e.created_at.isoformat().replace("+00:00", "Z") if e.created_at else ""
                })
            
            with open(output_path, "w") as f:
                json.dump(out, f, indent=2)
            logger.info("chain.exported", count=len(out), path=output_path)
