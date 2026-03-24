"""HMAC-based cryptographic signing for audit events, decision records,
and evidence bundles.

Uses HMAC-SHA256 with a server-side secret key. The signing key is derived
from the application's SECRET_KEY via HKDF to avoid key reuse with JWT
signing.

Verification is constant-time to prevent timing side-channels.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_SIGNING_CONTEXT = b"syndicateclaw-integrity-v1"


def derive_signing_key(secret_key: str) -> bytes:
    """Derive a dedicated signing key from the application secret via HKDF-like derivation."""
    return hashlib.sha256(_SIGNING_CONTEXT + secret_key.encode()).digest()


def sign_payload(payload: dict[str, Any], signing_key: bytes) -> str:
    """Compute HMAC-SHA256 over the canonical JSON of payload."""
    canonical = json.dumps(payload, sort_keys=True, default=str).encode()
    return hmac.new(signing_key, canonical, hashlib.sha256).hexdigest()


def verify_signature(payload: dict[str, Any], signature: str, signing_key: bytes) -> bool:
    """Verify HMAC-SHA256 signature. Constant-time comparison."""
    expected = sign_payload(payload, signing_key)
    return hmac.compare_digest(expected, signature)


def sign_record(record_data: dict[str, Any], signing_key: bytes) -> dict[str, Any]:
    """Add an integrity_signature field to a record dict. Returns a new dict."""
    signable = {k: v for k, v in record_data.items() if k != "integrity_signature"}
    signature = sign_payload(signable, signing_key)
    return {**record_data, "integrity_signature": signature}


def verify_record(record_data: dict[str, Any], signing_key: bytes) -> bool:
    """Verify the integrity_signature on a record dict."""
    signature = record_data.get("integrity_signature")
    if not signature:
        return False
    signable = {k: v for k, v in record_data.items() if k != "integrity_signature"}
    return verify_signature(signable, signature, signing_key)


class SigningKeyPair:
    """Ed25519 key pair for asymmetric signing.

    Provides non-repudiation: the private key signs, the public key
    verifies. The private key can be held in a KMS/HSM while the
    public key is distributed to verifiers.
    """

    def __init__(self, private_key_bytes: bytes | None = None) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        if private_key_bytes:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key
            self._private_key = load_pem_private_key(private_key_bytes, password=None)
        else:
            self._private_key = Ed25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()

    @property
    def public_key_pem(self) -> bytes:
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            PublicFormat,
        )
        return self._public_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    @property
    def private_key_pem(self) -> bytes:
        from cryptography.hazmat.primitives.serialization import (
            Encoding,
            NoEncryption,
            PrivateFormat,
        )
        return self._private_key.private_bytes(
            Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
        )

    def sign(self, payload: dict[str, Any]) -> str:
        """Sign canonical JSON with Ed25519. Returns hex-encoded signature."""
        canonical = json.dumps(payload, sort_keys=True, default=str).encode()
        sig = self._private_key.sign(canonical)
        return sig.hex()

    def verify(self, payload: dict[str, Any], signature_hex: str) -> bool:
        """Verify Ed25519 signature."""
        try:
            canonical = json.dumps(payload, sort_keys=True, default=str).encode()
            self._public_key.verify(bytes.fromhex(signature_hex), canonical)
            return True
        except Exception:
            return False

    @classmethod
    def from_public_key_pem(cls, pem: bytes) -> Ed25519Verifier:
        """Create a verify-only instance from a public key."""
        return Ed25519Verifier(pem)


class Ed25519Verifier:
    """Verify-only Ed25519 instance — holds only the public key."""

    def __init__(self, public_key_pem: bytes) -> None:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        self._public_key = load_pem_public_key(public_key_pem)

    def verify(self, payload: dict[str, Any], signature_hex: str) -> bool:
        try:
            canonical = json.dumps(payload, sort_keys=True, default=str).encode()
            self._public_key.verify(bytes.fromhex(signature_hex), canonical)
            return True
        except Exception:
            return False
