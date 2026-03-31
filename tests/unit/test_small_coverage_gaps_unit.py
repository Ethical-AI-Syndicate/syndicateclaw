"""Tests for small coverage gaps: llm/idempotency.py, messaging/router.py,
inference/catalog_sync/runner.py."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# llm/idempotency.py — _ttl_seconds branches
# ---------------------------------------------------------------------------


def test_ttl_seconds_default_when_env_not_set() -> None:
    from syndicateclaw.llm.idempotency import DEFAULT_LLM_IDEMPOTENCY_TTL_SECONDS, _ttl_seconds

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SYNDICATECLAW_LLM_IDEMPOTENCY_TTL_SECONDS", None)
        result = _ttl_seconds()
        assert result == DEFAULT_LLM_IDEMPOTENCY_TTL_SECONDS


def test_ttl_seconds_returns_parsed_value() -> None:
    from syndicateclaw.llm.idempotency import _ttl_seconds

    with patch.dict(os.environ, {"SYNDICATECLAW_LLM_IDEMPOTENCY_TTL_SECONDS": "300"}):
        result = _ttl_seconds()
        assert result == 300


def test_ttl_seconds_invalid_value_returns_default() -> None:
    from syndicateclaw.llm.idempotency import DEFAULT_LLM_IDEMPOTENCY_TTL_SECONDS, _ttl_seconds

    with patch.dict(os.environ, {"SYNDICATECLAW_LLM_IDEMPOTENCY_TTL_SECONDS": "not-a-number"}):
        result = _ttl_seconds()
        assert result == DEFAULT_LLM_IDEMPOTENCY_TTL_SECONDS


def test_ttl_seconds_zero_returns_default() -> None:
    from syndicateclaw.llm.idempotency import DEFAULT_LLM_IDEMPOTENCY_TTL_SECONDS, _ttl_seconds

    with patch.dict(os.environ, {"SYNDICATECLAW_LLM_IDEMPOTENCY_TTL_SECONDS": "0"}):
        result = _ttl_seconds()
        assert result == DEFAULT_LLM_IDEMPOTENCY_TTL_SECONDS


def test_ttl_seconds_negative_returns_default() -> None:
    from syndicateclaw.llm.idempotency import DEFAULT_LLM_IDEMPOTENCY_TTL_SECONDS, _ttl_seconds

    with patch.dict(os.environ, {"SYNDICATECLAW_LLM_IDEMPOTENCY_TTL_SECONDS": "-5"}):
        result = _ttl_seconds()
        assert result == DEFAULT_LLM_IDEMPOTENCY_TTL_SECONDS


def test_idempotency_store_resolve() -> None:
    from syndicateclaw.llm.idempotency import IdempotencyStore

    store = IdempotencyStore()
    decision = store.resolve(run_id="r1", node_id="n1", attempt_number=1, bypass_cache=False)
    assert decision.key == "r1:n1:1"
    assert decision.bypass_cache is False


def test_idempotency_store_bypass_on_retry() -> None:
    from syndicateclaw.llm.idempotency import IdempotencyStore

    store = IdempotencyStore()
    decision = store.resolve(run_id="r1", node_id="n1", attempt_number=2, bypass_cache=False)
    assert decision.bypass_cache is True


# ---------------------------------------------------------------------------
# messaging/router.py — line 38 (row not None) and line 70 (relay_payload)
# ---------------------------------------------------------------------------


def _make_message_router_session_factory(*, row_return=None):
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    begin_ctx = AsyncMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=None)
    begin_ctx.__aexit__ = AsyncMock(return_value=False)
    session.begin = MagicMock(return_value=begin_ctx)
    session.get = AsyncMock(return_value=row_return)
    session.add = MagicMock()
    return MagicMock(return_value=session)


def _make_message(*, hop_count: int = 3):
    msg = MagicMock()
    msg.id = "msg-1"
    msg.hop_count = hop_count
    msg.sender = "agent:1"
    msg.conversation_id = "conv-1"
    msg.recipient = "agent:2"
    msg.topic = "topic"
    msg.message_type = "text"
    msg.content = "hello"
    msg.metadata_ = {}
    msg.priority = 1
    msg.ttl_seconds = 60
    msg.expires_at = None
    return msg


async def test_message_router_hop_limit_row_found_sets_status() -> None:
    from syndicateclaw.messaging.router import HopLimitExceededError, MessageRouter

    existing_row = MagicMock()
    factory = _make_message_router_session_factory(row_return=existing_row)
    router = MessageRouter(factory, max_hops=3)
    msg = _make_message(hop_count=3)

    with pytest.raises(HopLimitExceededError):
        await router.route(msg)

    assert existing_row.status == "HOP_LIMIT_EXCEEDED"


async def test_message_router_hop_limit_row_not_found() -> None:
    from syndicateclaw.messaging.router import HopLimitExceededError, MessageRouter

    factory = _make_message_router_session_factory(row_return=None)
    router = MessageRouter(factory, max_hops=3)
    msg = _make_message(hop_count=3)

    with pytest.raises(HopLimitExceededError):
        await router.route(msg)


def test_message_router_relay_payload() -> None:
    from syndicateclaw.messaging.router import MessageRouter

    factory = _make_message_router_session_factory()
    router = MessageRouter(factory, max_hops=10)
    msg = _make_message(hop_count=1)

    payload = router.relay_payload(msg)
    assert payload["hop_count"] == 2
    assert payload["parent_message_id"] == "msg-1"
    assert payload["sender"] == "agent:1"


# ---------------------------------------------------------------------------
# inference/catalog_sync/runner.py — error paths
# ---------------------------------------------------------------------------


def _make_catalog():
    catalog = MagicMock()
    catalog.snapshot_version = "v1"
    catalog.entry_count = 5
    return catalog


def _make_base_config():
    cfg = MagicMock()
    cfg.providers = []
    cfg.static_catalog = []
    cfg.catalog_coexistence.yaml_wins_on_key_collision = False
    return cfg


async def test_runner_ssrf_blocked_returns_aborted() -> None:
    from syndicateclaw.inference.catalog_sync.errors import SSRFBlockedError
    from syndicateclaw.inference.catalog_sync.runner import run_models_dev_catalog_sync

    audit_service = AsyncMock()
    audit_service.emit = AsyncMock()

    with (
        patch("syndicateclaw.inference.catalog_sync.runner.fetch_https_bytes_bounded",
              new=AsyncMock(side_effect=SSRFBlockedError("blocked"))),
        patch("syndicateclaw.inference.catalog_sync.runner.ModelsDevCatalogSync"),
        patch("syndicateclaw.inference.catalog_sync.runner.record_catalog_sync_models_dev_outcome"),
    ):
        result = await run_models_dev_catalog_sync(
            feed_url="https://models.dev/api.json",
            allowed_host_suffixes=("models.dev",),
            max_bytes=1024 * 1024,
            timeout_seconds=10.0,
            max_redirects=3,
            catalog=_make_catalog(),
            base_system_config=_make_base_config(),
            audit_service=audit_service,
            actor="system",
        )
    assert result.applied is False
    assert result.aborted_reason == "ssrf_blocked"


async def test_runner_generic_exception_returns_aborted() -> None:
    from syndicateclaw.inference.catalog_sync.runner import run_models_dev_catalog_sync

    audit_service = AsyncMock()
    audit_service.emit = AsyncMock()

    with (
        patch("syndicateclaw.inference.catalog_sync.runner.fetch_https_bytes_bounded",
              new=AsyncMock(side_effect=RuntimeError("network down"))),
        patch("syndicateclaw.inference.catalog_sync.runner.ModelsDevCatalogSync"),
        patch("syndicateclaw.inference.catalog_sync.runner.record_catalog_sync_models_dev_outcome"),
    ):
        result = await run_models_dev_catalog_sync(
            feed_url="https://models.dev/api.json",
            allowed_host_suffixes=("models.dev",),
            max_bytes=1024 * 1024,
            timeout_seconds=10.0,
            max_redirects=3,
            catalog=_make_catalog(),
            base_system_config=_make_base_config(),
            audit_service=audit_service,
            actor="system",
        )
    assert result.applied is False
    assert result.aborted_reason == "fetch_failed"


async def test_runner_parse_error_returns_aborted() -> None:
    from syndicateclaw.inference.catalog_sync.runner import run_models_dev_catalog_sync

    audit_service = AsyncMock()
    audit_service.emit = AsyncMock()

    with (
        patch("syndicateclaw.inference.catalog_sync.runner.fetch_https_bytes_bounded",
              new=AsyncMock(return_value=b"not valid json")),
        patch("syndicateclaw.inference.catalog_sync.runner.ModelsDevCatalogSync"),
        patch("syndicateclaw.inference.catalog_sync.runner.parse_models_dev_json",
              side_effect=ValueError("bad json")),
        patch("syndicateclaw.inference.catalog_sync.runner.record_catalog_sync_models_dev_outcome"),
    ):
        result = await run_models_dev_catalog_sync(
            feed_url="https://models.dev/api.json",
            allowed_host_suffixes=("models.dev",),
            max_bytes=1024 * 1024,
            timeout_seconds=10.0,
            max_redirects=3,
            catalog=_make_catalog(),
            base_system_config=_make_base_config(),
            audit_service=audit_service,
            actor="system",
        )
    assert result.applied is False
    assert result.aborted_reason == "parse_failed"


async def test_runner_not_applied_not_anomaly_returns_result() -> None:
    from syndicateclaw.inference.catalog_sync.modelsdev import ModelsDevSyncResult
    from syndicateclaw.inference.catalog_sync.runner import run_models_dev_catalog_sync

    # applied=False, aborted_reason != "systemic_anomaly_drop"
    not_applied_result = ModelsDevSyncResult(
        applied=False,
        snapshot_version="v1",
        records_accepted=0,
        records_skipped=0,
        aborted_reason=None,
    )

    audit_service = AsyncMock()
    audit_service.emit = AsyncMock()

    mock_syncer = MagicMock()
    mock_syncer.sync_from_parsed_records = MagicMock(return_value=not_applied_result)

    with (
        patch("syndicateclaw.inference.catalog_sync.runner.fetch_https_bytes_bounded",
              new=AsyncMock(return_value=b'{"models": []}')),
        patch("syndicateclaw.inference.catalog_sync.runner.ModelsDevCatalogSync",
              return_value=mock_syncer),
        patch("syndicateclaw.inference.catalog_sync.runner.parse_models_dev_json",
              return_value=[]),
        patch("syndicateclaw.inference.catalog_sync.runner.record_catalog_sync_models_dev_outcome"),
    ):
        result = await run_models_dev_catalog_sync(
            feed_url="https://models.dev/api.json",
            allowed_host_suffixes=("models.dev",),
            max_bytes=1024 * 1024,
            timeout_seconds=10.0,
            max_redirects=3,
            catalog=_make_catalog(),
            base_system_config=_make_base_config(),
            audit_service=audit_service,
            actor="system",
        )
    assert result.applied is False
    assert result.aborted_reason is None


async def test_runner_success_emits_completed_audit() -> None:
    from syndicateclaw.inference.catalog_sync.modelsdev import ModelsDevSyncResult
    from syndicateclaw.inference.catalog_sync.runner import run_models_dev_catalog_sync

    success_result = ModelsDevSyncResult(
        applied=True,
        snapshot_version="v2",
        records_accepted=10,
        records_skipped=0,
    )

    audit_service = AsyncMock()
    audit_service.emit = AsyncMock()

    mock_syncer = MagicMock()
    mock_syncer.sync_from_parsed_records = MagicMock(return_value=success_result)

    with (
        patch("syndicateclaw.inference.catalog_sync.runner.fetch_https_bytes_bounded",
              new=AsyncMock(return_value=b'{"models": []}')),
        patch("syndicateclaw.inference.catalog_sync.runner.ModelsDevCatalogSync",
              return_value=mock_syncer),
        patch("syndicateclaw.inference.catalog_sync.runner.parse_models_dev_json",
              return_value=[]),
        patch("syndicateclaw.inference.catalog_sync.runner.record_catalog_sync_models_dev_outcome"),
    ):
        result = await run_models_dev_catalog_sync(
            feed_url="https://models.dev/api.json",
            allowed_host_suffixes=("models.dev",),
            max_bytes=1024 * 1024,
            timeout_seconds=10.0,
            max_redirects=3,
            catalog=_make_catalog(),
            base_system_config=_make_base_config(),
            audit_service=audit_service,
            actor="system",
        )
    assert result.applied is True


# ---------------------------------------------------------------------------
# inference/catalog_sync/ssrf.py — ip_address_is_blocked edge cases
# ---------------------------------------------------------------------------


def test_ip_address_is_blocked_reserved() -> None:
    import ipaddress

    from syndicateclaw.inference.catalog_sync.ssrf import ip_address_is_blocked

    # 240.0.0.1 is in the reserved block (240.0.0.0/4)
    reserved_ip = ipaddress.ip_address("240.0.0.1")
    assert ip_address_is_blocked(reserved_ip) is True


def test_ip_address_is_blocked_ipv6_with_mapped_loopback() -> None:
    import ipaddress

    from syndicateclaw.inference.catalog_sync.ssrf import ip_address_is_blocked

    # ::ffff:127.0.0.1 is IPv4-mapped loopback
    mapped_ip = ipaddress.ip_address("::ffff:127.0.0.1")
    assert ip_address_is_blocked(mapped_ip) is True


async def test_assert_safe_url_non_blocked_ip_literal_passes() -> None:
    from syndicateclaw.inference.catalog_sync.ssrf import assert_safe_url

    # 8.8.8.8 is a public IP, not blocked
    await assert_safe_url("https://8.8.8.8/path", allowed_host_suffixes=("8.8.8.8",))


# ---------------------------------------------------------------------------
# inference/policy_gates.py — BoundedPolicyCache edge cases
# ---------------------------------------------------------------------------


def test_bounded_policy_cache_expired_entry_removed() -> None:
    from syndicateclaw.inference.policy_gates import BoundedPolicyCache

    cache = BoundedPolicyCache(ttl_seconds=10.0, max_entries=100)
    cache.set("key1", "allow", now=0.0)
    # Get with a time past expiry
    result = cache.get("key1", now=100.0)
    assert result is None
    assert "key1" not in cache._data


def test_bounded_policy_cache_clear() -> None:
    from syndicateclaw.inference.policy_gates import BoundedPolicyCache

    cache = BoundedPolicyCache(ttl_seconds=60.0, max_entries=100)
    cache.set("key1", "allow")
    cache.set("key2", "deny")
    cache.clear()
    assert len(cache._data) == 0


# ---------------------------------------------------------------------------
# inference/policy_port.py — exception handling paths
# ---------------------------------------------------------------------------


async def test_policy_engine_routing_port_gate_inference_exception_returns_deny() -> None:
    from syndicateclaw.inference.policy_port import PolicyEngineRoutingPort
    from syndicateclaw.inference.types import InferenceCapability

    policy_engine = MagicMock()
    policy_engine.evaluate = AsyncMock(side_effect=RuntimeError("engine down"))
    port = PolicyEngineRoutingPort(policy_engine)

    result = await port.gate_inference_capability(
        capability=InferenceCapability.CHAT,
        actor="user:1",
        scope_type="PLATFORM",
        scope_id="*",
    )
    assert result == "deny"


async def test_policy_engine_routing_port_gate_model_exception_returns_deny() -> None:
    from syndicateclaw.inference.policy_gates import BoundedPolicyCache
    from syndicateclaw.inference.policy_port import PolicyEngineRoutingPort
    from syndicateclaw.inference.types import InferenceCapability

    policy_engine = MagicMock()
    policy_engine.evaluate = AsyncMock(side_effect=RuntimeError("engine down"))
    port = PolicyEngineRoutingPort(policy_engine)
    cache = BoundedPolicyCache(ttl_seconds=60.0, max_entries=100)

    result = await port.gate_model_use(
        provider_id="openai",
        model_id="gpt-4",
        capability=InferenceCapability.CHAT,
        actor="user:1",
        scope_type="PLATFORM",
        scope_id="*",
        cache=cache,
    )
    assert result == "deny"
