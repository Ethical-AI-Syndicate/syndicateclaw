from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_LLM_IDEMPOTENCY_TTL_SECONDS = 86400


def _ttl_seconds() -> int:
    raw = os.environ.get("SYNDICATECLAW_LLM_IDEMPOTENCY_TTL_SECONDS")
    if raw is None:
        return DEFAULT_LLM_IDEMPOTENCY_TTL_SECONDS
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_LLM_IDEMPOTENCY_TTL_SECONDS
    return parsed if parsed > 0 else DEFAULT_LLM_IDEMPOTENCY_TTL_SECONDS


@dataclass(frozen=True)
class IdempotencyDecision:
    key: str
    bypass_cache: bool
    ttl_seconds: int


class IdempotencyStore:
    """Builds idempotency keys/decisions for LLM node execution."""

    def resolve(
        self,
        *,
        run_id: str,
        node_id: str,
        attempt_number: int,
        bypass_cache: bool,
    ) -> IdempotencyDecision:
        key = f"{run_id}:{node_id}:{attempt_number}"
        should_bypass = bypass_cache or attempt_number > 1
        return IdempotencyDecision(
            key=key,
            bypass_cache=should_bypass,
            ttl_seconds=_ttl_seconds(),
        )
