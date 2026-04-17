from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

import jwt
import structlog

from syndicateclaw.config import Settings

logger = structlog.get_logger(__name__)
_JWKS_CLIENTS: dict[str, jwt.PyJWKClient] = {}
_JWKS_CLIENTS_LOCK = Lock()
_MIN_HS256_SECRET_BYTES = 32


class JWTError(Exception):
    """Unified JWT error for callers that previously depended on jose.JWTError."""


def validate_hs256_secret_strength(secret_key: str, *, key_name: str = "secret_key") -> None:
    """Enforce minimum key size for HS256 in production-like environments."""
    if len(secret_key.encode("utf-8")) < _MIN_HS256_SECRET_BYTES:
        raise ValueError(f"{key_name} must be at least {_MIN_HS256_SECRET_BYTES} bytes for HS256")


def _get_jwks_client(url: str) -> jwt.PyJWKClient:
    with _JWKS_CLIENTS_LOCK:
        client = _JWKS_CLIENTS.get(url)
        if client is None:
            client = jwt.PyJWKClient(url)
            _JWKS_CLIENTS[url] = client
        return client


def _get_secret_key() -> str:
    return Settings().secret_key


def create_access_token(
    actor: str,
    expires_delta: timedelta,
    *,
    org_id: str | None = None,
    org_role: str | None = None,
    secret_key: str | None = None,
    algorithm: str | None = None,
    private_key: Any = None,
) -> str:
    """Create a signed JWT with ``sub``, optional ``org_id`` / ``org_role``, and ``exp``.

    Permissions are resolved at request time via live RBAC (not embedded in the token).
    When *algorithm* is ``"EdDSA"`` and *private_key* is provided, the token
    is signed with an Ed25519 private key (asymmetric). Otherwise falls back
    to HS256 with the shared secret.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": actor,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    if org_id is not None:
        payload["org_id"] = org_id
    if org_role is not None:
        payload["org_role"] = org_role
    alg = algorithm or "HS256"
    if alg == "EdDSA" and private_key is not None:
        return jwt.encode(payload, private_key, algorithm="EdDSA")
    key = secret_key or _get_secret_key()
    return jwt.encode(payload, key, algorithm="HS256")


def decode_access_token(
    token: str,
    *,
    secret_key: str | None = None,
    secondary_secret_key: str | None = None,
    algorithm: str | None = None,
    public_key: Any = None,
    audience: str | None = None,
    oidc_jwks_url: str | None = None,
    issuer: str | None = None,
) -> dict[str, Any]:
    """Decode and verify a JWT, returning its claims.

    Supports RS256 via OIDC JWKS, HS256 (symmetric), and EdDSA (asymmetric).
    When multiple verification sources are configured, tries EdDSA first
    (preferred local asymmetric), then OIDC/JWKS, then falls back to HS256.
    Algorithms are fixed allowlists per attempt — never taken from the token header.

    Raises ``JWTError`` on invalid / expired tokens.
    """
    decode_options = {
        "verify_signature": True,
        "verify_exp": True,
        "verify_nbf": True,
        "require": ["exp"],
    }
    alg = algorithm or "HS256"
    algorithms_to_try: list[tuple[str, Any]] = []
    last_error: Exception | None = None

    if public_key is not None:
        algorithms_to_try.append(("EdDSA", public_key))
    if oidc_jwks_url:
        try:
            signing_key = _get_jwks_client(oidc_jwks_url).get_signing_key_from_jwt(token)
            algorithms_to_try.append(("RS256", signing_key.key))
        except Exception as exc:  # pragma: no cover - exercised via decode failure path
            last_error = exc
    if alg != "EdDSA" or public_key is None:
        key = secret_key or _get_secret_key()
        algorithms_to_try.append(("HS256", key))
        if secondary_secret_key:
            algorithms_to_try.append(("HS256", secondary_secret_key))

    for try_alg, try_key in algorithms_to_try:
        try:
            kw: dict[str, Any] = {
                "algorithms": [try_alg],
                "options": decode_options,
            }
            if audience:
                kw["audience"] = audience
            if try_alg == "RS256" and issuer:
                kw["issuer"] = issuer
            return jwt.decode(token, try_key, **kw)
        except jwt.exceptions.PyJWTError as exc:
            last_error = exc
            continue

    logger.warning("auth.token_decode_failed")
    raise JWTError(str(last_error)) from last_error


_API_KEY_ACTORS: dict[str, str] = {
    "sc-dev-key-001": "dev-agent",
    "sc-dev-key-002": "dev-admin",
}


def verify_api_key(api_key: str) -> str | None:
    """Return the actor name associated with *api_key*, or ``None`` if invalid."""
    actor = _API_KEY_ACTORS.get(api_key)
    if actor is None:
        logger.warning("auth.invalid_api_key")
    return actor
