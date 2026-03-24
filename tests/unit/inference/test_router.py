"""Tests for InferenceRouter determinism, fallback ordering, and policy prefilter."""

from __future__ import annotations

import pytest

from syndicateclaw.inference.catalog import ModelCatalog
from syndicateclaw.inference.config_schema import StaticCatalogEntry
from syndicateclaw.inference.errors import InferenceRoutingError
from syndicateclaw.inference.policy_gates import BoundedPolicyCache
from syndicateclaw.inference.registry import ProviderRegistry
from syndicateclaw.inference.router import InferenceRouter, PolicyRoutingPort
from syndicateclaw.inference.types import (
    ChatInferenceRequest,
    ChatMessage,
    CircuitState,
    EmbeddingInferenceRequest,
    InferenceCapability,
    ModelCost,
    ModelDescriptor,
    ModelLimits,
    RoutingFailureReason,
)
from tests.unit.inference.fixtures import minimal_system, provider, static_chat_row


class _AllowAll(PolicyRoutingPort):
    def gate_inference_capability(self, **kwargs):
        return "allow"

    def gate_model_use(self, **kwargs):
        return "allow"


class _DenySpecificModel(PolicyRoutingPort):
    def __init__(self, denied: set[str]) -> None:
        self._denied = denied

    def gate_inference_capability(self, **kwargs):
        return "allow"

    def gate_model_use(self, *, model_id: str, **kwargs):
        return "deny" if model_id in self._denied else "allow"


def _chat(**kwargs):
    return ChatInferenceRequest(
        messages=[ChatMessage(role="user", content="hi")],
        actor="a:1",
        trace_id="t1",
        **kwargs,
    )


def test_deterministic_same_decision_except_ulid() -> None:
    d1 = ModelDescriptor(
        model_id="m1",
        name="m1",
        provider_id="p",
        limits=ModelLimits(context_window=8192),
    )
    d2 = ModelDescriptor(
        model_id="m2",
        name="m2",
        provider_id="p",
        limits=ModelLimits(context_window=8192),
    )
    sys = minimal_system(
        provider("p"),
        static=(
            StaticCatalogEntry(
                provider_id="p",
                model_id="m1",
                capability=InferenceCapability.CHAT,
                descriptor=d1,
            ),
            StaticCatalogEntry(
                provider_id="p",
                model_id="m2",
                capability=InferenceCapability.CHAT,
                descriptor=d2,
            ),
        ),
    )
    cat = ModelCatalog()
    cat.replace_from_yaml_static(sys, snapshot_version="v")
    reg = ProviderRegistry(sys)
    router = InferenceRouter(sys.routing)
    cache = BoundedPolicyCache(ttl_seconds=60.0, max_entries=128)
    req = _chat()
    a1 = router.route(
        req,
        system=sys,
        registry=reg,
        catalog=cat,
        policy=_AllowAll(),
        policy_cache=cache,
    )
    a2 = router.route(
        req,
        system=sys,
        registry=reg,
        catalog=cat,
        policy=_AllowAll(),
        policy_cache=cache,
    )
    assert a1.selected_provider_id == a2.selected_provider_id
    assert a1.selected_model_id == a2.selected_model_id
    assert a1.fallback_chain == a2.fallback_chain


def test_fallback_chain_order_by_score_then_lex() -> None:
    cheap = ModelDescriptor(
        model_id="cheap",
        name="cheap",
        provider_id="p",
        cost=ModelCost(input_per_million=1.0, output_per_million=1.0),
        limits=ModelLimits(context_window=100000),
    )
    pricey = ModelDescriptor(
        model_id="pricey",
        name="pricey",
        provider_id="p",
        cost=ModelCost(input_per_million=999.0, output_per_million=999.0),
        limits=ModelLimits(context_window=100000),
    )
    sys = minimal_system(
        provider("p"),
        static=(
            StaticCatalogEntry(
                provider_id="p",
                model_id="cheap",
                capability=InferenceCapability.CHAT,
                descriptor=cheap,
            ),
            StaticCatalogEntry(
                provider_id="p",
                model_id="pricey",
                capability=InferenceCapability.CHAT,
                descriptor=pricey,
            ),
        ),
    )
    cat = ModelCatalog()
    cat.replace_from_yaml_static(sys, snapshot_version="v")
    reg = ProviderRegistry(sys)
    router = InferenceRouter(sys.routing)
    cache = BoundedPolicyCache(ttl_seconds=60.0, max_entries=128)
    d = router.route(
        _chat(),
        system=sys,
        registry=reg,
        catalog=cat,
        policy=_AllowAll(),
        policy_cache=cache,
    )
    assert d.selected_model_id == "cheap"
    assert d.fallback_chain == [("p", "pricey")]


def test_policy_prefilter_drops_denied_model() -> None:
    sys = minimal_system(
        provider("p"),
        static=(
            static_chat_row("p", "bad"),
            static_chat_row("p", "good"),
        ),
    )
    cat = ModelCatalog()
    cat.replace_from_yaml_static(sys, snapshot_version="v")
    reg = ProviderRegistry(sys)
    router = InferenceRouter(sys.routing)
    cache = BoundedPolicyCache(ttl_seconds=60.0, max_entries=128)
    d = router.route(
        _chat(),
        system=sys,
        registry=reg,
        catalog=cat,
        policy=_DenySpecificModel({"bad"}),
        policy_cache=cache,
    )
    assert d.selected_model_id == "good"


def test_pin_required_without_model_or_pin_raises() -> None:
    sys = minimal_system(provider("p"), static=(static_chat_row("p", "m"),))
    cat = ModelCatalog()
    cat.replace_from_yaml_static(sys, snapshot_version="v")
    reg = ProviderRegistry(sys)
    router = InferenceRouter(sys.routing)
    cache = BoundedPolicyCache(ttl_seconds=60.0, max_entries=128)
    req = EmbeddingInferenceRequest(
        inputs=["x"],
        actor="a",
        trace_id="t",
    )
    with pytest.raises(InferenceRoutingError) as ei:
        router.route(
            req,
            system=sys,
            registry=reg,
            catalog=cat,
            policy=_AllowAll(),
            policy_cache=cache,
        )
    assert ei.value.failure_reason == RoutingFailureReason.PIN_MISMATCH


def test_circuit_open_skips_provider() -> None:
    sys = minimal_system(
        provider("open"),
        provider("closed"),
        static=(
            static_chat_row("open", "m"),
            static_chat_row("closed", "m"),
        ),
    )
    cat = ModelCatalog()
    cat.replace_from_yaml_static(sys, snapshot_version="v")
    reg = ProviderRegistry(sys)
    now = 1000.0
    for _ in range(10):
        reg.record_circuit_failure("open", now=now)
        now += 0.01
    assert reg.circuit_state("open", now=now) == CircuitState.OPEN
    router = InferenceRouter(sys.routing)
    cache = BoundedPolicyCache(ttl_seconds=60.0, max_entries=128)
    d = router.route(
        _chat(),
        system=sys,
        registry=reg,
        catalog=cat,
        policy=_AllowAll(),
        policy_cache=cache,
        now=now,
    )
    assert d.selected_provider_id == "closed"
