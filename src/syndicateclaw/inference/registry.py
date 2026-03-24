"""ProviderRegistry — YAML-backed provider definitions + ephemeral runtime state.

Runtime state (health, circuit, rate-limit cooldown, operator disable) lives only in memory.
It must never become an alternate source of topology vs YAML (Phase 1).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Protocol, runtime_checkable

from syndicateclaw.inference.config_schema import ProviderSystemConfig
from syndicateclaw.inference.types import CircuitState, ProviderConfig, ProviderStatus


class SlidingWindowCircuitBreaker:
    """Sliding-window failures → OPEN; success from HALF_OPEN → CLOSED."""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        window_seconds: float = 60.0,
        open_seconds: float = 30.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._window_seconds = window_seconds
        self._open_seconds = open_seconds
        self._fail_times: deque[float] = deque()
        self._state = CircuitState.CLOSED
        self._opened_at: float | None = None

    def state(self, now: float) -> CircuitState:
        if (
            self._state == CircuitState.OPEN
            and self._opened_at is not None
            and now - self._opened_at >= self._open_seconds
        ):
            self._state = CircuitState.HALF_OPEN
        return self._state

    def record_failure(self, now: float) -> None:
        self._fail_times.append(now)
        cutoff = now - self._window_seconds
        while self._fail_times and self._fail_times[0] < cutoff:
            self._fail_times.popleft()
        if len(self._fail_times) >= self._failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = now

    def record_success(self, now: float) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._fail_times.clear()
            self._opened_at = None
        elif self._state == CircuitState.CLOSED:
            self._fail_times.clear()


class _Ephemeral:
    __slots__ = (
        "health",
        "circuit",
        "rate_limit_cooldown_until",
        "runtime_disabled",
    )

    def __init__(self) -> None:
        self.health: ProviderStatus = ProviderStatus.ACTIVE
        self.circuit: SlidingWindowCircuitBreaker = SlidingWindowCircuitBreaker()
        self.rate_limit_cooldown_until: float | None = None
        self.runtime_disabled: bool = False


@runtime_checkable
class ProviderRegistryRead(Protocol):
    """Read-only surface for InferenceRouter (no mutation hooks)."""

    def get_provider(self, provider_id: str) -> ProviderConfig | None: ...

    def circuit_state(self, provider_id: str, *, now: float | None = None) -> CircuitState: ...

    def health_status(self, provider_id: str) -> ProviderStatus: ...

    def is_rate_limit_cooldown(self, provider_id: str, *, now: float | None = None) -> bool: ...

    def is_runtime_disabled(self, provider_id: str) -> bool: ...


class ProviderRegistry:
    """In-memory registry: provider definitions from a config snapshot + ephemeral fields."""

    def __init__(self, config: ProviderSystemConfig) -> None:
        self._config = config
        self._providers: dict[str, ProviderConfig] = {p.id: p for p in config.providers}
        self._lock = threading.RLock()
        self._ephemeral: dict[str, _Ephemeral] = {pid: _Ephemeral() for pid in self._providers}

    @property
    def system_config(self) -> ProviderSystemConfig:
        return self._config

    def get_provider(self, provider_id: str) -> ProviderConfig | None:
        return self._providers.get(provider_id)

    def list_provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._providers))

    def circuit_state(self, provider_id: str, *, now: float | None = None) -> CircuitState:
        t = time.monotonic() if now is None else now
        with self._lock:
            ep = self._ephemeral.get(provider_id)
            if ep is None:
                return CircuitState.CLOSED
            return ep.circuit.state(t)

    def health_status(self, provider_id: str) -> ProviderStatus:
        with self._lock:
            ep = self._ephemeral.get(provider_id)
            if ep is None:
                return ProviderStatus.UNAVAILABLE
            return ep.health

    def is_rate_limit_cooldown(self, provider_id: str, *, now: float | None = None) -> bool:
        t = time.monotonic() if now is None else now
        with self._lock:
            ep = self._ephemeral.get(provider_id)
            if ep is None or ep.rate_limit_cooldown_until is None:
                return False
            return t < ep.rate_limit_cooldown_until

    def is_runtime_disabled(self, provider_id: str) -> bool:
        with self._lock:
            ep = self._ephemeral.get(provider_id)
            return ep.runtime_disabled if ep else True

    # --- mutation (ProviderService / ops — not called by InferenceRouter) ---

    def set_health(self, provider_id: str, status: ProviderStatus) -> None:
        with self._lock:
            ep = self._ephemeral.get(provider_id)
            if ep is not None:
                ep.health = status

    def set_runtime_disabled(self, provider_id: str, disabled: bool) -> None:
        with self._lock:
            ep = self._ephemeral.get(provider_id)
            if ep is not None:
                ep.runtime_disabled = disabled

    def set_rate_limit_cooldown_until(self, provider_id: str, until: float | None) -> None:
        with self._lock:
            ep = self._ephemeral.get(provider_id)
            if ep is not None:
                ep.rate_limit_cooldown_until = until

    def record_circuit_failure(self, provider_id: str, *, now: float | None = None) -> None:
        t = time.monotonic() if now is None else now
        with self._lock:
            ep = self._ephemeral.get(provider_id)
            if ep is not None:
                ep.circuit.record_failure(t)

    def record_circuit_success(self, provider_id: str, *, now: float | None = None) -> None:
        t = time.monotonic() if now is None else now
        with self._lock:
            ep = self._ephemeral.get(provider_id)
            if ep is not None:
                ep.circuit.record_success(t)
