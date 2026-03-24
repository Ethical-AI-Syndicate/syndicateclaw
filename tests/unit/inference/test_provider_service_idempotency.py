"""ProviderService + IdempotencyStore (Postgres); skips without SYNDICATECLAW_TEST_DATABASE_URL."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from syndicateclaw.inference.catalog import ModelCatalog
from syndicateclaw.inference.config_loader import ProviderConfigLoader
from syndicateclaw.inference.config_schema import StaticCatalogEntry
from syndicateclaw.inference.errors import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    InferenceExecutionError,
)
from syndicateclaw.inference.idempotency import IdempotencyStore
from syndicateclaw.inference.registry import ProviderRegistry
from syndicateclaw.inference.service import ProviderService
from syndicateclaw.inference.types import (
    AdapterProtocol,
    ChatInferenceRequest,
    ChatInferenceResponse,
    ChatMessage,
    InferenceCapability,
    ModelDescriptor,
    ProviderConfig,
    ProviderType,
)
from syndicateclaw.models import PolicyEffect
from tests.unit.inference.fixtures import minimal_system

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _make_svc(
    tmp_path,
    inference_session_factory,
    *,
    stale_after: float = 3600.0,
) -> ProviderService:
    sys = minimal_system(
        ProviderConfig(
            id="p1",
            name="P",
            provider_type=ProviderType.LOCAL,
            adapter_protocol=AdapterProtocol.OPENAI_COMPATIBLE,
            base_url="http://test",
            capabilities=[InferenceCapability.CHAT],
        ),
        static=(
            StaticCatalogEntry(
                provider_id="p1",
                model_id="m1",
                capability=InferenceCapability.CHAT,
                descriptor=ModelDescriptor(model_id="m1", name="M", provider_id="p1"),
            ),
        ),
    )
    yml = tmp_path / "p.yaml"
    yml.write_text(yaml.safe_dump(sys.model_dump(mode="json")))
    loader = ProviderConfigLoader(yml)
    loader.load_and_activate()

    cat = ModelCatalog()
    cat.replace_from_yaml_static(loader.current()[0], snapshot_version=loader.current()[1])
    reg = ProviderRegistry(loader.current()[0])
    audit = AsyncMock()
    audit.emit = AsyncMock()
    pe = MagicMock()

    async def allow_eval(*_a, **_k):
        m = MagicMock()
        m.effect = PolicyEffect.ALLOW
        return m

    pe.evaluate = allow_eval

    store = IdempotencyStore(inference_session_factory, stale_after_seconds=stale_after)
    return ProviderService(
        loader=loader,
        catalog=cat,
        registry=reg,
        policy_engine=pe,
        audit_service=audit,
        idempotency_store=store,
    )


async def test_same_key_same_hash_replays_without_second_adapter_call(
    inference_session_factory, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    calls: list[int] = []

    class FakeAdapter:
        async def infer_chat(self, cfg, req, *, api_key, bearer_token):
            calls.append(1)
            return ChatInferenceResponse(
                inference_id="",
                provider_id=cfg.id,
                model_id="m1",
                content="once",
            )

    monkeypatch.setattr(
        "syndicateclaw.inference.service.adapter_for",
        lambda _p: FakeAdapter(),
    )
    svc = _make_svc(tmp_path, inference_session_factory)

    base = dict(
        messages=[ChatMessage(role="user", content="hi")],
        actor="a",
        trace_id="t",
        provider_id="p1",
        model_id="m1",
        idempotency_key="idem-same",
    )
    r1 = await svc.infer_chat(ChatInferenceRequest(**base))
    r2 = await svc.infer_chat(ChatInferenceRequest(**base))
    assert r1.content == r2.content == "once"
    assert len(calls) == 1


async def test_different_hash_raises_conflict(
    inference_session_factory, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    class FakeAdapter:
        async def infer_chat(self, cfg, req, *, api_key, bearer_token):
            return ChatInferenceResponse(
                inference_id="",
                provider_id=cfg.id,
                model_id="m1",
                content="x",
            )

    monkeypatch.setattr(
        "syndicateclaw.inference.service.adapter_for",
        lambda _p: FakeAdapter(),
    )
    svc = _make_svc(tmp_path, inference_session_factory)

    await svc.infer_chat(
        ChatInferenceRequest(
            messages=[ChatMessage(role="user", content="a")],
            actor="a",
            trace_id="t",
            provider_id="p1",
            model_id="m1",
            idempotency_key="idem-hash",
        )
    )
    with pytest.raises(IdempotencyConflictError):
        await svc.infer_chat(
            ChatInferenceRequest(
                messages=[ChatMessage(role="user", content="b")],
                actor="a",
                trace_id="t",
                provider_id="p1",
                model_id="m1",
                idempotency_key="idem-hash",
            )
        )


async def test_second_caller_in_progress(
    inference_session_factory, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    gate = asyncio.Event()

    class SlowAdapter:
        async def infer_chat(self, cfg, req, *, api_key, bearer_token):
            await gate.wait()
            return ChatInferenceResponse(
                inference_id="",
                provider_id=cfg.id,
                model_id="m1",
                content="done",
            )

    monkeypatch.setattr(
        "syndicateclaw.inference.service.adapter_for",
        lambda _p: SlowAdapter(),
    )
    svc = _make_svc(tmp_path, inference_session_factory)

    async def first() -> None:
        await svc.infer_chat(
            ChatInferenceRequest(
                messages=[ChatMessage(role="user", content="x")],
                actor="a",
                trace_id="t1",
                provider_id="p1",
                model_id="m1",
                idempotency_key="idem-slow",
            )
        )

    t1 = asyncio.create_task(first())
    await asyncio.sleep(0.05)
    with pytest.raises(IdempotencyInProgressError):
        await svc.infer_chat(
            ChatInferenceRequest(
                messages=[ChatMessage(role="user", content="x")],
                actor="a",
                trace_id="t2",
                provider_id="p1",
                model_id="m1",
                idempotency_key="idem-slow",
            )
        )
    gate.set()
    await t1


async def test_failure_replay_returns_same_execution_error(
    inference_session_factory, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from syndicateclaw.inference.types import ErrorCategory

    class FailingAdapter:
        async def infer_chat(self, cfg, req, *, api_key, bearer_token):
            raise InferenceExecutionError(
                "boom",
                category=ErrorCategory.PROVIDER,
                retryable=False,
            )

    monkeypatch.setattr(
        "syndicateclaw.inference.service.adapter_for",
        lambda _p: FailingAdapter(),
    )
    svc = _make_svc(tmp_path, inference_session_factory)

    req = ChatInferenceRequest(
        messages=[ChatMessage(role="user", content="x")],
        actor="a",
        trace_id="t",
        provider_id="p1",
        model_id="m1",
        idempotency_key="idem-fail",
    )
    with pytest.raises(InferenceExecutionError):
        await svc.infer_chat(req)
    with pytest.raises(InferenceExecutionError) as ei:
        await svc.infer_chat(req)
    assert "boom" in str(ei.value)
