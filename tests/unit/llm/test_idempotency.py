from __future__ import annotations

from syndicateclaw.llm.idempotency import IdempotencyStore


def test_idempotency_key_uses_run_node_attempt() -> None:
    store = IdempotencyStore()
    decision = store.resolve(
        run_id="run-1",
        node_id="node-1",
        attempt_number=1,
        bypass_cache=False,
    )
    assert decision.key == "run-1:node-1:1"
    assert decision.bypass_cache is False


def test_idempotency_bypass_on_retry_attempt() -> None:
    store = IdempotencyStore()
    decision = store.resolve(
        run_id="run-1",
        node_id="node-1",
        attempt_number=2,
        bypass_cache=False,
    )
    assert decision.bypass_cache is True


def test_idempotency_bypass_cache_flag() -> None:
    store = IdempotencyStore()
    decision = store.resolve(
        run_id="run-1",
        node_id="node-1",
        attempt_number=1,
        bypass_cache=True,
    )
    assert decision.bypass_cache is True


def test_idempotency_default_ttl() -> None:
    store = IdempotencyStore()
    decision = store.resolve(
        run_id="run-1",
        node_id="node-1",
        attempt_number=1,
        bypass_cache=False,
    )
    assert decision.ttl_seconds == 86400
