from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import jwt
import structlog

from syndicateclaw.config import Settings

logger = structlog.get_logger(__name__)


class JWTError(Exception):
    """Unified JWT error for callers that previously depended on jose.JWTError."""


def _get_secret_key() -> str:
    return Settings().secret_key


def create_access_token(
    actor: str,
    permissions: list[str],
    expires_delta: timedelta,
    *,
    secret_key: str | None = None,
    algorithm: str | None = None,
    private_key: Any = None,
) -> str:
    """Create a signed JWT containing actor identity and permissions.

    When *algorithm* is ``"EdDSA"`` and *private_key* is provided, the token
    is signed with an Ed25519 private key (asymmetric). Otherwise falls back
    to HS256 with the shared secret.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": actor,
        "permissions": permissions,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
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
) -> dict[str, Any]:
    """Decode and verify a JWT, returning its claims.

    Supports HS256 (symmetric) and EdDSA (asymmetric). When both keys are
    provided, tries EdDSA first (preferred), then falls back to HS256.
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

    if public_key is not None:
        algorithms_to_try.append(("EdDSA", public_key))
    if alg != "EdDSA" or public_key is None:
        key = secret_key or _get_secret_key()
        algorithms_to_try.append(("HS256", key))
        if secondary_secret_key:
            algorithms_to_try.append(("HS256", secondary_secret_key))

    last_error: Exception | None = None
    for try_alg, try_key in algorithms_to_try:
        try:
            kw: dict[str, Any] = {
                "algorithms": [try_alg],
                "options": decode_options,
            }
            if audience:
                kw["audience"] = audience
            return cast(dict[str, Any], jwt.decode(token, try_key, **kw))
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
