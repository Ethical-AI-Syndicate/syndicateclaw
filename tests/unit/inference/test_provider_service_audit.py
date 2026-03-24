"""ProviderService emits audit + metrics hooks (mocked adapter + httpx)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syndicateclaw.inference.config_loader import ProviderConfigLoader
from syndicateclaw.inference.config_schema import StaticCatalogEntry
from syndicateclaw.inference.registry import ProviderRegistry
from syndicateclaw.inference.service import ProviderService
from syndicateclaw.inference.types import (
    AdapterProtocol,
    ChatInferenceRequest,
    ChatMessage,
    InferenceCapability,
    ModelDescriptor,
    ProviderConfig,
    ProviderType,
)
from syndicateclaw.models import AuditEventType
from tests.unit.inference.fixtures import minimal_system


@pytest.mark.asyncio
async def test_infer_chat_emits_started_and_completed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
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
    import yaml

    yml.write_text(yaml.safe_dump(sys.model_dump(mode="json")))
    loader = ProviderConfigLoader(yml)
    loader.load_and_activate()

    from syndicateclaw.inference.catalog import ModelCatalog

    cat = ModelCatalog()
    cat.replace_from_yaml_static(loader.current()[0], snapshot_version=loader.current()[1])
    reg = ProviderRegistry(loader.current()[0])

    audit = AsyncMock()
    audit.emit = AsyncMock()

    pe = MagicMock()

    async def allow_eval(*a, **k):
        m = MagicMock()
        m.effect = __import__(
            "syndicateclaw.models", fromlist=["PolicyEffect"]
        ).PolicyEffect.ALLOW
        return m

    pe.evaluate = allow_eval

    svc = ProviderService(
        loader=loader,
        catalog=cat,
        registry=reg,
        policy_engine=pe,
        audit_service=audit,
    )

    class FakeAdapter:
        async def infer_chat(self, cfg, req, *, api_key, bearer_token):
            from syndicateclaw.inference.types import ChatInferenceResponse

            return ChatInferenceResponse(
                inference_id="",
                provider_id=cfg.id,
                model_id="m1",
                content="ok",
            )

    monkeypatch.setattr(
        "syndicateclaw.inference.service.adapter_for",
        lambda _p: FakeAdapter(),
    )

    req = ChatInferenceRequest(
        messages=[ChatMessage(role="user", content="hi")],
        actor="a",
        trace_id="t1",
        provider_id="p1",
        model_id="m1",
    )
    out = await svc.infer_chat(req)
    assert out.content == "ok"

    types_emitted = [c.args[0].event_type for c in audit.emit.call_args_list]
    assert AuditEventType.INFERENCE_STARTED in types_emitted
    assert AuditEventType.INFERENCE_COMPLETED in types_emitted
