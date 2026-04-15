import json
import hashlib
from datetime import datetime, UTC
from typing import Any
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from syndicateclaw.db.models import PermitState as DBPermitState
from syndicateclaw.models import ExecutionPermit, PermitStateEnum
from syndicateclaw.security.signing import Ed25519Verifier
from typing import Protocol

class PermitIssuer(Protocol):
    async def issue_permit(self, target_type: str, target_id: str, action: str, payload_hash: str) -> ExecutionPermit: ...

logger = structlog.get_logger(__name__)

class PermitConsumptionError(RuntimeError):
    pass

class PermitService:
    """
    Validates and atomically consumes ExecutionPermits to ensure authorization integrity.
    """
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], verifier: Ed25519Verifier = None):
        self._session_factory = session_factory
        self._verifier = verifier

    def _canonical_payload_hash(self, payload: dict[str, Any]) -> str:
        """Computes the expected payload_hash for the action context."""
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()

    async def validate_and_consume(
        self,
        permit: ExecutionPermit,
        target_type: str,
        target_id: str,
        action: str,
        payload: dict[str, Any]
    ) -> None:
        """
        Validates the permit signature, scope, expiry, and atomically consumes it.
        Fail-closed: Raises PermitConsumptionError on any ambiguity or validation failure.
        """
        if self._verifier is None:
            raise PermitConsumptionError("Permit validation requires an Ed25519Verifier")

        # 1. Scope and Action Validation
        if permit.target_type != target_type:
            raise PermitConsumptionError(f"Scope mismatch: target_type '{permit.target_type}' != '{target_type}'")
        if permit.target_id != target_id and permit.target_id != "*":
            raise PermitConsumptionError(f"Scope mismatch: target_id '{permit.target_id}' != '{target_id}'")
        if permit.action != action:
            raise PermitConsumptionError(f"Action mismatch: '{permit.action}' != '{action}'")

        # 2. Payload Binding Validation
        # If payload_hash is "*", it means payload binding is relaxed (e.g. general read permit)
        # Otherwise, verify payload hash.
        if permit.payload_hash != "*":
            expected_hash = self._canonical_payload_hash(payload)
            if permit.payload_hash != expected_hash:
                raise PermitConsumptionError("Payload binding mismatch")

        # 3. Expiry Validation
        now = datetime.now(UTC)
        if permit.expires_at < now:
            raise PermitConsumptionError("Permit expired")

        # 4. Signature Verification
        # The signature covers the permit fields (excluding signature/state)
        signable_dict = {
            "permit_id": permit.permit_id,
            "key_id": permit.key_id,
            "issued_at": permit.issued_at.isoformat(),
            "expires_at": permit.expires_at.isoformat(),
            "tenant_id": permit.tenant_id,
            "actor_id": permit.actor_id,
            "target_type": permit.target_type,
            "target_id": permit.target_id,
            "action": permit.action,
            "payload_hash": permit.payload_hash
        }
        if not self._verifier.verify(signable_dict, permit.signature):
            raise PermitConsumptionError("Invalid permit signature")

        # 5. Atomic Consumption (Replay Protection)
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                select(DBPermitState)
                .where(DBPermitState.permit_id == permit.permit_id)
                .with_for_update()
            )
            state_row = result.scalar_one_or_none()
            
            if state_row is None:
                # First time seeing this permit
                state_row = DBPermitState(
                    permit_id=permit.permit_id,
                    tenant_id=permit.tenant_id,
                    state=PermitStateEnum.ISSUED.value
                )
                session.add(state_row)
                await session.flush()
                
            if state_row.state == PermitStateEnum.CONSUMED.value:
                raise PermitConsumptionError("Permit already consumed (Replay Attempt)")

            # Consume it
            state_row.state = PermitStateEnum.CONSUMED.value
            state_row.consumed_at = now
            
        logger.info("permit.consumed", permit_id=permit.permit_id, action=action)
