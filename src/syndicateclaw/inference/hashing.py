"""Canonical SHA-256 hashing for idempotency and audit payload digests."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(obj: Any) -> bytes:
    """Stable JSON: sorted keys, compact separators, UTF-8."""
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def canonical_json_hash(obj: Any) -> str:
    """SHA-256 hex digest of canonical JSON representation."""
    return hashlib.sha256(canonical_json_bytes(obj)).hexdigest()
