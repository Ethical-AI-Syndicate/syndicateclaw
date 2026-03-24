"""Schema-based redaction for sensitive fields in workflow state.

Prevents accidental exposure of credentials, tokens, and PII that
may be placed in workflow state by tools or user input.
"""

from __future__ import annotations

import copy
import re
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

SENSITIVE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)password"),
    re.compile(r"(?i)secret"),
    re.compile(r"(?i)token"),
    re.compile(r"(?i)api[_-]?key"),
    re.compile(r"(?i)credential"),
    re.compile(r"(?i)private[_-]?key"),
    re.compile(r"(?i)auth"),
    re.compile(r"(?i)ssn"),
    re.compile(r"(?i)credit[_-]?card"),
    re.compile(r"(?i)cvv"),
]

REDACTED = "[REDACTED]"


def redact_state(
    state: dict[str, Any],
    *,
    extra_patterns: list[str] | None = None,
    allowlist: set[str] | None = None,
) -> dict[str, Any]:
    """Return a deep copy of state with sensitive fields redacted.

    Args:
        state: The workflow state dict.
        extra_patterns: Additional regex patterns to match as sensitive.
        allowlist: Field names that should never be redacted (e.g. "_run_id").

    Returns:
        A new dict with sensitive values replaced by "[REDACTED]".
    """
    patterns = list(SENSITIVE_PATTERNS)
    if extra_patterns:
        patterns.extend(re.compile(p) for p in extra_patterns)

    safe_allow = allowlist or set()
    result = copy.deepcopy(state)
    _redact_recursive(result, patterns, safe_allow, path="")
    return result


def _redact_recursive(
    obj: Any,
    patterns: list[re.Pattern[str]],
    allowlist: set[str],
    path: str,
) -> None:
    if isinstance(obj, dict):
        for key in list(obj.keys()):
            full_path = f"{path}.{key}" if path else key
            if key in allowlist or full_path in allowlist:
                continue
            if _is_sensitive_key(key, patterns):
                obj[key] = REDACTED
            else:
                _redact_recursive(obj[key], patterns, allowlist, full_path)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _redact_recursive(item, patterns, allowlist, f"{path}[{i}]")


def _is_sensitive_key(key: str, patterns: list[re.Pattern[str]]) -> bool:
    return any(p.search(key) for p in patterns)
