"""ControlPlane runtime-authority re-validation client.

SDD-CLAW-RUNTIME-BOUNDARY-001, section 3 (preferred verification model). Claw
does NOT reimplement ControlPlane signing canonicalization. Instead it
re-validates an authority reference + binding tuple against a running ControlPlane
endpoint and treats the response as the authority decision. ControlPlane
unavailable is a denial in production mode (fail-closed).

This module defines:
  * ``ValidationStatus`` / ``ValidationResult`` — the re-validation response
    contract.
  * ``ControlPlaneAuthorityValidator`` — the protocol Claw calls.
  * ``HttpControlPlaneValidator`` — production adapter (POSTs to the CP
    runtime-authority endpoint); any transport failure ⇒ ``UNAVAILABLE``.
  * ``InMemoryControlPlaneValidator`` — a test harness implementing the SAME
    contract over an in-process permit registry (for the boundary proof). It does
    not weaken the contract: it returns active/expired/revoked/consumed/denied/
    unavailable exactly as a real ControlPlane re-validation would.
"""

from __future__ import annotations

import dataclasses
import enum
import json
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse


class ValidationStatus(enum.StrEnum):
    ALLOW = "allow"
    DENIED = "denied"
    EXPIRED = "expired"
    REVOKED = "revoked"
    CONSUMED = "consumed"
    UNAVAILABLE = "unavailable"


@dataclasses.dataclass(frozen=True)
class ValidationResult:
    """Result of a ControlPlane runtime-authority re-validation call."""

    status: ValidationStatus
    permit_id: str | None = None
    validated_at: str = dataclasses.field(default_factory=lambda: datetime.now(UTC).isoformat())
    detail: str = ""

    @property
    def allowed(self) -> bool:
        return self.status is ValidationStatus.ALLOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "permit_id": self.permit_id,
            "validated_at": self.validated_at,
            "detail": self.detail,
        }


@dataclasses.dataclass(frozen=True)
class AuthorityBinding:
    """The binding tuple Claw asks ControlPlane to re-validate the permit against."""

    actor: str
    tenant_id: str
    project_id: str
    workspace_id: str
    tool_identity: str
    action: str
    resource_scope: str
    approval_id: str | None
    correlation_id: str

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@runtime_checkable
class ControlPlaneAuthorityValidator(Protocol):
    def validate(self, authority_reference: str, binding: AuthorityBinding) -> ValidationResult:
        """Re-validate the permit reference + binding. Never raises for transport
        problems — those map to ``ValidationStatus.UNAVAILABLE`` so the boundary
        can fail closed deterministically."""
        ...


class HttpControlPlaneValidator:
    """Production adapter: POST the authority reference + binding to ControlPlane's
    runtime-authority endpoint. Any transport/HTTP failure ⇒ UNAVAILABLE (the
    boundary then fails closed in production mode).

    NOTE: not exercised against a live Go ControlPlane in this pass; the boundary
    proof uses ``InMemoryControlPlaneValidator`` over the same contract. Wiring
    against a live endpoint is deployment configuration.
    """

    def __init__(self, endpoint: str, *, timeout_s: float = 5.0, session: Any = None) -> None:
        # Fail-closed config: the ControlPlane endpoint MUST be http(s). This also
        # ensures the urllib fallback can only ever open an http(s) URL (never
        # file://, ftp://, etc.).
        scheme = urlparse(endpoint).scheme.lower()
        if scheme not in {"http", "https"}:
            raise ValueError(f"ControlPlane endpoint must use http or https, got {scheme!r}")
        self._endpoint = endpoint.rstrip("/")
        self._timeout = timeout_s
        self._session = session  # injected requests-like client; optional

    def validate(self, authority_reference: str, binding: AuthorityBinding) -> ValidationResult:
        payload = {"authority_reference": authority_reference, "binding": binding.to_dict()}
        try:
            if self._session is None:  # pragma: no cover - exercised via injection
                import urllib.request

                req = urllib.request.Request(
                    f"{self._endpoint}/v1/runtime-authority/validate",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"content-type": "application/json"},
                    method="POST",
                )
                # Endpoint scheme is validated to http(s) in __init__, so this
                # urlopen cannot open a local/file scheme. nosec B310: scheme-checked.
                with urllib.request.urlopen(  # nosec B310
                    req, timeout=self._timeout
                ) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
            else:
                r = self._session.post(
                    f"{self._endpoint}/v1/runtime-authority/validate",
                    json=payload,
                    timeout=self._timeout,
                )
                if r.status_code >= 500:
                    return ValidationResult(
                        ValidationStatus.UNAVAILABLE, detail=f"http {r.status_code}"
                    )
                body = r.json()
        except Exception as exc:  # transport failure ⇒ fail-closed input
            return ValidationResult(ValidationStatus.UNAVAILABLE, detail=str(exc)[:200])
        try:
            status = ValidationStatus(str(body.get("status", "denied")))
        except ValueError:
            status = ValidationStatus.DENIED
        return ValidationResult(
            status=status,
            permit_id=body.get("permit_id"),
            detail=str(body.get("detail", "")),
        )


@dataclasses.dataclass
class _PermitState:
    binding: AuthorityBinding
    status: ValidationStatus = ValidationStatus.ALLOW
    single_use: bool = False
    consumed: bool = False


class InMemoryControlPlaneValidator:
    """Test harness implementing the ControlPlane re-validation contract.

    Faithful to production fail-closed semantics:
      * unknown reference ⇒ DENIED;
      * binding mismatch ⇒ DENIED (ControlPlane would not match the permit);
      * expired/revoked ⇒ that status;
      * single-use permit already consumed (replay) ⇒ CONSUMED;
      * ``set_unavailable(True)`` ⇒ UNAVAILABLE (simulated outage).
    """

    def __init__(self) -> None:
        self._permits: dict[str, _PermitState] = {}
        self._unavailable = False
        self.calls: list[tuple[str, AuthorityBinding]] = []

    def register(
        self,
        authority_reference: str,
        binding: AuthorityBinding,
        *,
        status: ValidationStatus = ValidationStatus.ALLOW,
        single_use: bool = False,
    ) -> None:
        self._permits[authority_reference] = _PermitState(
            binding=binding, status=status, single_use=single_use
        )

    def set_unavailable(self, value: bool) -> None:
        self._unavailable = value

    def validate(self, authority_reference: str, binding: AuthorityBinding) -> ValidationResult:
        self.calls.append((authority_reference, binding))
        if self._unavailable:
            return ValidationResult(ValidationStatus.UNAVAILABLE, detail="controlplane unreachable")
        state = self._permits.get(authority_reference)
        if state is None:
            return ValidationResult(ValidationStatus.DENIED, detail="unknown authority reference")
        if state.status is not ValidationStatus.ALLOW:
            return ValidationResult(
                state.status, permit_id=authority_reference, detail=f"permit {state.status}"
            )
        # ControlPlane re-validates the binding against the issued permit.
        if state.binding.to_dict() != binding.to_dict():
            return ValidationResult(
                ValidationStatus.DENIED,
                permit_id=authority_reference,
                detail="binding does not match issued permit",
            )
        if state.single_use and state.consumed:
            return ValidationResult(
                ValidationStatus.CONSUMED,
                permit_id=authority_reference,
                detail="single-use permit already consumed",
            )
        if state.single_use:
            state.consumed = True
        return ValidationResult(
            ValidationStatus.ALLOW, permit_id=authority_reference, detail="active"
        )
