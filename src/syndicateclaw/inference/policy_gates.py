"""Policy cache and routing-time gate helpers (bounded, TTL, fail-closed hooks)."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Literal

PolicyGateAnswer = Literal["allow", "deny"]


class BoundedPolicyCache:
    """TTL + LRU-bounded cache for policy outcomes (routing must stay bounded)."""

    def __init__(self, *, ttl_seconds: float, max_entries: int) -> None:
        self._ttl = ttl_seconds
        self._max = max(1, max_entries)
        self._data: OrderedDict[str, tuple[float, PolicyGateAnswer]] = OrderedDict()

    def get(self, key: str, now: float | None = None) -> PolicyGateAnswer | None:
        t = time.monotonic() if now is None else now
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, answer = item
        if expires_at <= t:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return answer

    def set(self, key: str, answer: PolicyGateAnswer, now: float | None = None) -> None:
        t = time.monotonic() if now is None else now
        expires = t + self._ttl
        self._data[key] = (expires, answer)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()
