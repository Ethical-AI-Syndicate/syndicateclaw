import functools
import inspect
import json
import hashlib
from typing import Any, Callable, TypeVar, Awaitable, Protocol, runtime_checkable
from enum import StrEnum
import logging
from datetime import datetime, UTC

from syndicateclaw.security.signing import SigningKeyPair
from syndicateclaw.models import AuditEvent, AuditEventType, ExecutionPermit
from syndicateclaw.auth.permit_service import PermitService, PermitConsumptionError

logger = logging.getLogger(__name__)

class ExecutionAction(StrEnum):
    TOOL_EXECUTE = "tool.execute"
    WORKFLOW_NODE_EXECUTE = "workflow.node.execute"
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    MEMORY_DELETE = "memory.delete"
    CONNECTOR_MESSAGE_HANDLE = "connector.message.handle"
    CONNECTOR_REPLY_SEND = "connector.reply.send"
    TASK_RESUME = "task.resume"

@runtime_checkable
class AuditService(Protocol):
    async def emit(self, event: AuditEvent) -> AuditEvent: ...

T = TypeVar("T")

def canonical_hash(prev_hash: str, event_type: str, actor: str, payload: str, created_at: str) -> str:
    """Computes the canonical SHA-256 hash for an audit event (Phase 3)."""
    signable = f"{prev_hash}|{event_type}|{actor}|{payload}|{created_at}"
    return hashlib.sha256(signable.encode()).hexdigest()

class ProtectedExecutionProvider:
    """
    Provider for the mandatory structural interceptor for all Claw execution paths.
    Enforces synchronous audit coupling and canonical signing (Phase 3).
    Enforces permit/authorization integrity (Phase 4).
    """
    
    def __init__(self, audit_service: AuditService = None, signer: SigningKeyPair = None, key_id: str = "default", permit_service: PermitService = None):
        self._audit_service = audit_service
        self._signer = signer
        self._key_id = key_id
        self._permit_service = permit_service
        self._last_hash = "0000000000000000000000000000000000000000000000000000000000000000" # Genesis anchor
        self._next_seq = 1

    async def execute(
        self, 
        action: ExecutionAction, 
        actor: str, 
        payload: dict[str, Any], 
        func: Callable[..., Awaitable[T]], 
        *args: Any, 
        permit: ExecutionPermit | None = None,
        target_type: str = "system",
        target_id: str = "system",
        **kwargs: Any
    ) -> T:
        """
        The mandatory structural interceptor.
        Signs events with Ed25519 before execution.
        Validates permits before execution (Phase 4).
        """
        
        if not self._audit_service:
            raise RuntimeError("Control Violation: Audit Service required for protected execution")
        
        # 0. Permit Validation (Invariant 4 / Phase 4)
        if self._permit_service:
            if permit is None:
                raise RuntimeError(f"Authorization Denied: Permit required for action {action}")
            try:
                await self._permit_service.validate_and_consume(
                    permit=permit,
                    target_type=target_type,
                    target_id=target_id,
                    action=str(action),
                    payload=payload
                )
            except PermitConsumptionError as e:
                logger.critical(f"AUTHORIZATION FAILURE: Blocking execution of {action} for {actor}: {str(e)}")
                raise RuntimeError(f"Execution blocked: authorization failure: {str(e)}")
        elif permit:
             # Even if permit service is omitted (e.g. tests), if a permit is given we should Ideally validate it.
             pass

        # 1. Prepare Authoritative Event (Phase 3)
        event_type_str = "execution.start"
        created_at = datetime.now(UTC).isoformat()
        sanitized_payload = json.dumps(self._sanitize_payload(payload), sort_keys=True)
        
        event_hash = canonical_hash(self._last_hash, event_type_str, actor, sanitized_payload, created_at)
        
        signature = None
        if self._signer:
            signature = self._signer.sign({"hash": event_hash}) 

        # 2. Synchronous Audit Start (Invariant 3)
        try:
            event = AuditEvent.new(
                event_type=AuditEventType.NODE_STARTED, # Map to existing enum or use custom
                actor=actor,
                resource_type="execution",
                resource_id=str(action),
                action="start",
                details={
                    "action": str(action),
                    "request_context": sanitized_payload
                },
                sequence_number=self._next_seq,
                previous_hash=self._last_hash,
                event_hash=event_hash,
                key_id=self._key_id,
                signature=signature,
                integrity_chain="auth"
            )
            await self._audit_service.emit(event)
            self._last_hash = event_hash # Advance local pointer
            self._next_seq += 1
            
        except Exception as e:
            logger.critical(f"AUDIT FAILURE: Blocking execution of {action} for {actor}: {str(e)}")
            raise RuntimeError(f"Execution blocked: audit failure: {str(e)}")

        try:
            # 3. Execution
            result = await func(*args, **kwargs)
            return result
            
        except Exception as e:
            raise

    def _sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Prevents sensitive data (tokens, keys) from leaking into audit start events."""
        # TODO: Implement deep scrubbing based on known sensitive keys
        return {k: v for k, v in payload.items() if k not in ("token", "secret", "password", "key")}

def protected_execution(action: ExecutionAction):
    """
    Decorator for wrapping service methods in the protected execution boundary.
    """
    def decorator(func: Callable[..., Awaitable[T]]):
        @functools.wraps(func)
        async def wrapper(self, *args, **kwargs):
            if not hasattr(self, "protected_execution_provider") or self.protected_execution_provider is None:
                raise RuntimeError(f"Structural Violation: {self.__class__.__name__} lacks a protected_execution_provider")
            
            # Extract common metadata for audit
            actor = getattr(self, "current_actor", "system")
            
            # Construct a descriptive payload for the start event
            # We try to find tool name or run_id in args/kwargs
            payload = {"method": func.__name__}
            if args:
                payload["args_summary"] = [str(a)[:50] for a in args[:2]]
            if kwargs:
                payload["kwargs_keys"] = list(kwargs.keys())

            # Phase 4 Permit extraction
            permit = kwargs.pop("permit", None)
            target_type = kwargs.pop("target_type", "system")
            target_id = kwargs.pop("target_id", "system")

            return await self.protected_execution_provider.execute(
                action, actor, payload, func, self, *args, permit=permit, target_type=target_type, target_id=target_id, **kwargs
            )
        return wrapper
    return decorator
