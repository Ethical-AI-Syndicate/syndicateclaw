"""Unit tests for ProviderService idempotency helpers and _resolve_auth (no external LLM)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from syndicateclaw.inference.errors import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    IdempotencyTerminalKeyError,
    InferenceExecutionError,
)
from syndicateclaw.inference.service import ProviderService, _resolve_auth
from syndicateclaw.inference.types import (
    ChatInferenceRequest,
    ChatInferenceResponse,
    ChatMessage,
    EmbeddingInferenceRequest,
    EmbeddingInferenceResponse,
    InferenceEnvelopeStatus,
)


def _chat_req(**kwargs: object) -> ChatInferenceRequest:
    base = {
        "messages": [ChatMessage(role="user", content="hello")],
        "actor": "actor-1",
        "trace_id": "trace-1",
    }
    base.update(kwargs)
    return ChatInferenceRequest(**base)


def _emb_req(**kwargs: object) -> EmbeddingInferenceRequest:
    base = {
        "inputs": ["a"],
        "actor": "actor-1",
        "trace_id": "trace-1",
    }
    base.update(kwargs)
    return EmbeddingInferenceRequest(**base)


def _make_service(store: AsyncMock) -> ProviderService:
    return ProviderService(
        loader=MagicMock(),
        catalog=MagicMock(),
        registry=MagicMock(),
        policy_engine=MagicMock(),
        audit_service=MagicMock(),
        idempotency_store=store,
    )


def test_resolve_auth_no_auth_block() -> None:
    cfg = MagicMock()
    cfg.auth = None
    assert _resolve_auth(cfg) == (None, None)


def test_resolve_auth_missing_env_var() -> None:
    cfg = MagicMock()
    cfg.auth = MagicMock()
    cfg.auth.env_var = "UNSET_INFERENCE_KEY_XYZ"
    assert _resolve_auth(cfg) == (None, None)


def test_resolve_auth_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = MagicMock()
    cfg.auth = MagicMock()
    cfg.auth.env_var = "TEST_INFERENCE_SECRET_ABC"
    monkeypatch.setenv("TEST_INFERENCE_SECRET_ABC", "sekret")
    assert _resolve_auth(cfg) == ("sekret", None)


@pytest.mark.asyncio
async def test_idempotency_chat_begin_no_key_returns_ulid() -> None:
    store = AsyncMock()
    svc = _make_service(store)
    binding = MagicMock()
    binding.system_config_version = "v1"
    req = _chat_req()
    iid, finalize, replay = await svc._idempotency_chat_begin(req, binding)
    assert len(iid) == 26
    assert finalize is False
    assert replay is None
    store.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_idempotency_chat_replay_completed_success() -> None:
    store = AsyncMock()
    row = MagicMock()
    row.inference_id = "inf-done"
    row.status = InferenceEnvelopeStatus.COMPLETED.value
    row.result_json = {
        "inference_id": "inf-done",
        "provider_id": "p1",
        "model_id": "m1",
        "content": "cached",
    }
    store.acquire = AsyncMock(return_value=(row, False))
    store.mark_executing = AsyncMock()

    svc = _make_service(store)
    binding = MagicMock()
    binding.system_config_version = "v1"
    req = _chat_req(idempotency_key="idem-1")

    iid, finalize, replay = await svc._idempotency_chat_begin(req, binding)
    assert iid == "inf-done"
    assert finalize is False
    assert replay is not None
    assert replay.content == "cached"
    store.mark_executing.assert_not_called()


@pytest.mark.asyncio
async def test_idempotency_chat_replay_completed_failed_raises() -> None:
    store = AsyncMock()
    row = MagicMock()
    row.inference_id = "inf-bad"
    row.status = InferenceEnvelopeStatus.COMPLETED.value
    row.result_json = {"_failed": True, "detail": "provider blew up"}
    store.acquire = AsyncMock(return_value=(row, False))

    svc = _make_service(store)
    binding = MagicMock()
    binding.system_config_version = "v1"
    req = _chat_req(idempotency_key="idem-2")

    with pytest.raises(InferenceExecutionError, match="provider blew up"):
        await svc._idempotency_chat_begin(req, binding)


@pytest.mark.asyncio
async def test_idempotency_chat_in_progress_raises() -> None:
    store = AsyncMock()
    row = MagicMock()
    row.inference_id = "inf-run"
    row.status = InferenceEnvelopeStatus.EXECUTING.value
    row.result_json = None
    store.acquire = AsyncMock(return_value=(row, False))

    svc = _make_service(store)
    binding = MagicMock()
    binding.system_config_version = "v1"
    req = _chat_req(idempotency_key="idem-3")

    with pytest.raises(IdempotencyInProgressError):
        await svc._idempotency_chat_begin(req, binding)


@pytest.mark.asyncio
async def test_idempotency_chat_failed_terminal_raises() -> None:
    store = AsyncMock()
    row = MagicMock()
    row.inference_id = "inf-dead"
    row.status = InferenceEnvelopeStatus.FAILED.value
    row.result_json = None
    row.failure_reason = "bad luck"
    store.acquire = AsyncMock(return_value=(row, False))

    svc = _make_service(store)
    binding = MagicMock()
    binding.system_config_version = "v1"
    req = _chat_req(idempotency_key="idem-4")

    with pytest.raises(IdempotencyTerminalKeyError, match="bad luck"):
        await svc._idempotency_chat_begin(req, binding)


@pytest.mark.asyncio
async def test_idempotency_chat_new_marks_executing() -> None:
    store = AsyncMock()
    row = MagicMock()
    row.inference_id = "inf-new"
    store.acquire = AsyncMock(return_value=(row, True))
    store.mark_executing = AsyncMock()

    svc = _make_service(store)
    binding = MagicMock()
    binding.system_config_version = "v1"
    req = _chat_req(idempotency_key="idem-5")

    iid, finalize, replay = await svc._idempotency_chat_begin(req, binding)
    assert iid == "inf-new"
    assert finalize is True
    assert replay is None
    store.mark_executing.assert_awaited_once_with("inf-new")


@pytest.mark.asyncio
async def test_idempotency_chat_acquire_conflict_propagates() -> None:
    store = AsyncMock()
    store.acquire = AsyncMock(side_effect=IdempotencyConflictError("hash mismatch"))
    svc = _make_service(store)
    binding = MagicMock()
    binding.system_config_version = "v1"
    req = _chat_req(idempotency_key="conflict-key")
    with pytest.raises(IdempotencyConflictError):
        await svc._idempotency_chat_begin(req, binding)


@pytest.mark.asyncio
async def test_idempotency_embedding_failed_with_detail_raises() -> None:
    store = AsyncMock()
    row = MagicMock()
    row.inference_id = "e2"
    row.status = InferenceEnvelopeStatus.FAILED.value
    row.result_json = {"_failed": True, "detail": "embed failed"}
    row.failure_reason = None
    store.acquire = AsyncMock(return_value=(row, False))

    svc = _make_service(store)
    binding = MagicMock()
    binding.system_config_version = "v1"
    req = _emb_req(idempotency_key="idem-fail")

    with pytest.raises(InferenceExecutionError, match="embed failed"):
        await svc._idempotency_embedding_begin(req, binding)


@pytest.mark.asyncio
async def test_idempotency_embedding_in_progress_raises() -> None:
    store = AsyncMock()
    row = MagicMock()
    row.inference_id = "e3"
    row.status = InferenceEnvelopeStatus.PENDING.value
    row.result_json = None
    store.acquire = AsyncMock(return_value=(row, False))

    svc = _make_service(store)
    binding = MagicMock()
    binding.system_config_version = "v1"
    req = _emb_req(idempotency_key="idem-ip")

    with pytest.raises(IdempotencyInProgressError):
        await svc._idempotency_embedding_begin(req, binding)


@pytest.mark.asyncio
async def test_infer_chat_propagates_and_updates_idempotency_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AsyncMock()
    row = MagicMock()
    row.inference_id = "inf-zzz"
    store.acquire = AsyncMock(return_value=(row, True))
    store.mark_executing = AsyncMock()
    store.update_failed = AsyncMock()

    svc = _make_service(store)

    binding = MagicMock()
    binding.system_config_version = "v1"
    monkeypatch.setattr(
        "syndicateclaw.inference.service.ExecutionBinding.capture",
        staticmethod(lambda _loader, _cat: binding),
    )

    async def _boom(
        self: ProviderService,
        req: ChatInferenceRequest,
        b: object,
        inference_id: str,
        idem_finalize: bool,
    ) -> ChatInferenceResponse:
        raise RuntimeError("downstream")

    monkeypatch.setattr(ProviderService, "_infer_chat_execute", _boom)

    req = _chat_req(idempotency_key="idem-err")
    with pytest.raises(RuntimeError, match="downstream"):
        await svc.infer_chat(req)

    store.update_failed.assert_awaited()
    call_kw = store.update_failed.await_args
    assert call_kw[0][0] == "inf-zzz"
    payload = call_kw[1]["result_json"]
    assert payload["_failed"] is True
    assert "downstream" in payload["detail"]


@pytest.mark.asyncio
async def test_idempotency_chat_failed_status_with_failed_json_raises() -> None:
    store = AsyncMock()
    row = MagicMock()
    row.inference_id = "inf-f2"
    row.status = InferenceEnvelopeStatus.FAILED.value
    row.result_json = {"_failed": True, "detail": "terminal chat fail"}
    row.failure_reason = None
    store.acquire = AsyncMock(return_value=(row, False))

    svc = _make_service(store)
    binding = MagicMock()
    binding.system_config_version = "v1"
    req = _chat_req(idempotency_key="idem-fail-json")

    with pytest.raises(InferenceExecutionError, match="terminal chat fail"):
        await svc._idempotency_chat_begin(req, binding)


@pytest.mark.asyncio
async def test_infer_embedding_propagates_and_updates_idempotency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = AsyncMock()
    row = MagicMock()
    row.inference_id = "emb-zzz"
    store.acquire = AsyncMock(return_value=(row, True))
    store.mark_executing = AsyncMock()
    store.update_failed = AsyncMock()

    svc = _make_service(store)

    binding = MagicMock()
    binding.system_config_version = "v1"
    monkeypatch.setattr(
        "syndicateclaw.inference.service.ExecutionBinding.capture",
        staticmethod(lambda _loader, _cat: binding),
    )

    async def _boom(
        self: ProviderService,
        req: EmbeddingInferenceRequest,
        b: object,
        inference_id: str,
        idem_finalize: bool,
    ) -> EmbeddingInferenceResponse:
        raise RuntimeError("embedding adapter down")

    monkeypatch.setattr(ProviderService, "_infer_embedding_execute", _boom)

    req = _emb_req(idempotency_key="idem-emb-fail")
    with pytest.raises(RuntimeError, match="embedding adapter down"):
        await svc.infer_embedding(req)

    store.update_failed.assert_awaited()


@pytest.mark.asyncio
async def test_idempotency_embedding_replay_completed() -> None:
    store = AsyncMock()
    row = MagicMock()
    row.inference_id = "e1"
    row.status = InferenceEnvelopeStatus.COMPLETED.value
    row.result_json = {
        "inference_id": "e1",
        "provider_id": "p",
        "model_id": "emb",
        "embeddings": [[0.1]],
        "dimensions": 1,
    }
    store.acquire = AsyncMock(return_value=(row, False))

    svc = _make_service(store)
    binding = MagicMock()
    binding.system_config_version = "v1"
    req = _emb_req(idempotency_key="idem-e")

    _iid, _fin, replay = await svc._idempotency_embedding_begin(req, binding)
    assert replay is not None
    assert replay.dimensions == 1
