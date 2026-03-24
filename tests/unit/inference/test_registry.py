"""Tests for ProviderRegistry ephemeral state (circuit, health, cooldown, disable)."""

from __future__ import annotations

import time

from syndicateclaw.inference.registry import ProviderRegistry, SlidingWindowCircuitBreaker
from syndicateclaw.inference.types import CircuitState, ProviderStatus
from tests.unit.inference.fixtures import minimal_system, provider


def test_sliding_window_circuit_opens_then_half_open() -> None:
    cb = SlidingWindowCircuitBreaker(
        failure_threshold=3,
        window_seconds=60.0,
        open_seconds=0.05,
    )
    t0 = 1000.0
    assert cb.state(t0) == CircuitState.CLOSED
    cb.record_failure(t0)
    cb.record_failure(t0 + 0.01)
    assert cb.state(t0 + 0.02) == CircuitState.CLOSED
    cb.record_failure(t0 + 0.02)
    assert cb.state(t0 + 0.03) == CircuitState.OPEN
    t_open = t0 + 0.03
    assert cb.state(t_open + 0.06) == CircuitState.HALF_OPEN


def test_registry_runtime_disable_excludes_from_reads() -> None:
    sys = minimal_system(provider("a"))
    reg = ProviderRegistry(sys)
    assert reg.is_runtime_disabled("a") is False
    reg.set_runtime_disabled("a", True)
    assert reg.is_runtime_disabled("a") is True


def test_registry_health_and_cooldown() -> None:
    sys = minimal_system(provider("a"))
    reg = ProviderRegistry(sys)
    reg.set_health("a", ProviderStatus.DEGRADED)
    assert reg.health_status("a") == ProviderStatus.DEGRADED
    now = time.monotonic()
    reg.set_rate_limit_cooldown_until("a", now + 10.0)
    assert reg.is_rate_limit_cooldown("a", now=now + 1.0) is True
    assert reg.is_rate_limit_cooldown("a", now=now + 11.0) is False


def test_registry_circuit_hooks() -> None:
    sys = minimal_system(provider("a"))
    reg = ProviderRegistry(sys)
    now = 1000.0
    for _ in range(5):
        reg.record_circuit_failure("a", now=now)
        now += 0.01
    assert reg.circuit_state("a", now=now) == CircuitState.OPEN
    reg.record_circuit_success("a", now=now + 100.0)
    assert reg.circuit_state("a", now=now + 100.0) in (
        CircuitState.HALF_OPEN,
        CircuitState.CLOSED,
    )
