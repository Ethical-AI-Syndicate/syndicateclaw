"""mTLS identity extraction from reverse proxy headers."""

from dataclasses import dataclass
from typing import Any


class MtlsIdentityError(Exception):
    """Error extracting or validating mTLS identity."""


@dataclass
class MtlsIdentity:
    """
    Identity extracted from mTLS client certificate.

    Typically injected by reverse proxy (nginx, envoy) via headers:
    - X-Client-Cert-DN: Distinguished Name
    - X-Client-Cert-SHA256: Certificate SHA256 fingerprint
    - X-Client-Cert-Verify: Verification status
    """

    subject_dn: str | None = None
    issuer_dn: str | None = None
    serial_number: str | None = None
    sha256_fingerprint: str | None = None
    not_before: str | None = None
    not_after: str | None = None
    verified: bool = False


class MtlsIdentityExtractor:
    """
    Extract mTLS identity from reverse proxy headers.

    In a Kubernetes environment, this is typically set by an ingress controller
    or service mesh (Istio, Linkerd) that terminates TLS.
    """

    HEADER_SUBJECT_DN = "X-Client-Cert-Subject-DN"
    HEADER_ISSUER_DN = "X-Client-Cert-Issuer-DN"
    HEADER_SERIAL = "X-Client-Cert-Serial"
    HEADER_SHA256 = "X-Client-Cert-SHA256"
    HEADER_NOT_BEFORE = "X-Client-Cert-Not-Before"
    HEADER_NOT_AFTER = "X-Client-Cert-Not-After"
    HEADER_VERIFY = "X-Client-Cert-Verify"

    def extract(self, headers: dict[str, str]) -> MtlsIdentity | None:
        """
        Extract mTLS identity from request headers.

        Args:
            headers: Request headers dictionary

        Returns:
            MtlsIdentity if found, None otherwise

        Raises:
            MtlsIdentityError: If identity is present but invalid
        """
        if self.HEADER_SHA256 not in headers:
            return None

        verify_status = headers.get(self.HEADER_VERIFY, "").lower()
        if verify_status != "success":
            raise MtlsIdentityError(f"Client certificate verification failed: {verify_status}")

        return MtlsIdentity(
            subject_dn=headers.get(self.HEADER_SUBJECT_DN),
            issuer_dn=headers.get(self.HEADER_ISSUER_DN),
            serial_number=headers.get(self.HEADER_SERIAL),
            sha256_fingerprint=headers.get(self.HEADER_SHA256),
            not_before=headers.get(self.HEADER_NOT_BEFORE),
            not_after=headers.get(self.HEADER_NOT_AFTER),
            verified=True,
        )

    def extract_actor(self, identity: MtlsIdentity) -> str:
        """
        Derive an actor identifier from mTLS identity.

        Args:
            identity: The mTLS identity

        Returns:
            Actor identifier string

        Raises:
            MtlsIdentityError: If no identity available to derive actor
        """
        if identity.subject_dn:
            return self._dn_to_actor(identity.subject_dn)
        if identity.sha256_fingerprint:
            return f"mtls:{identity.sha256_fingerprint[:16]}"
        raise MtlsIdentityError("No identity available to derive actor")

    def _dn_to_actor(self, dn: str) -> str:
        """Convert Distinguished Name to actor identifier."""
        import re

        match = re.search(r"CN=([^,]+)", dn, re.IGNORECASE)
        if match:
            return match.group(1).lower().replace(" ", "_")
        return "unknown"
