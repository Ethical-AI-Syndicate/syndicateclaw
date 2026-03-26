"""JWT revocation list (Redis-backed, optional)."""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def is_token_revoked(redis: Any | None, jti: str) -> bool:
    """Return True if *jti* is present in the revocation set.

    If Redis is unavailable or errors, returns False (revocation check skipped).
    """
    if redis is None or not jti:
        return False
    try:
        key = f"jwt:revoked:{jti}"
        val = await redis.get(key)
        return val is not None and val != ""
    except Exception:
        logger.warning("auth.revocation_check_failed", jti_prefix=jti[:8], exc_info=True)
        return False
