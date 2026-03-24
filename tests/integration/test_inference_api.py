"""FastAPI integration tests for inference and provider routes.

Validates HTTP-layer contracts: routing, authz registry alignment, streaming,
error serialization, and trace propagation — with ProviderService mocked so
tests do not call external LLM endpoints.
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from syndicateclaw.api.dependencies import get_provider_service
from syndicateclaw.authz.route_registry import get_route_spec
from syndicateclaw.inference.errors import (
    IdempotencyConflictError,
    InferenceApprovalRequiredError,
    InferenceDeniedError,
    InferenceExecutionError,
    InferenceRoutingError,
    InferenceValidationError,
)
from syndicateclaw.inference.types import (
    ChatInferenceRequest,
    ChatInferenceResponse,
    EmbeddingInferenceResponse,
    ErrorCategory,
    RoutingFailureReason,
)

pytestmark = pytest.mark.integration

INFERENCE_HTTP_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/inference/chat"),
        ("POST", "/api/v1/inference/embedding"),
        ("POST", "/api/v1/inference/chat/stream"),
        ("GET", "/api/v1/providers/"),
    }
)


def _collect_api_route_keys(app) -> set[tuple[str, str]]:
    from fastapi.routing import APIRoute

    out: set[tuple[str, str]] = set()
    for r in app.routes:
        if isinstance(r, APIRoute):
            for m in r.methods:
                if m in ("HEAD", "OPTIONS"):
                    continue
                out.add((m, r.path))
    return out


class _RecordingMockProviderService:
    """Minimal stand-in for ProviderService (routes call only these methods)."""

    def __init__(self) -> None:
        self.chat_calls: list[ChatInferenceRequest] = []
        self.embedding_calls: list = []
        self.stream_calls: list[ChatInferenceRequest] = []
        self.raise_on_chat: BaseException | None = None

    async def infer_chat(self, req: ChatInferenceRequest) -> ChatInferenceResponse:
        self.chat_calls.append(req)
        if self.raise_on_chat is not None:
            raise self.raise_on_chat
        return ChatInferenceResponse(
            inference_id="integ-i1",
            provider_id="p-mock",
            model_id="m-mock",
            content="mocked-reply",
        )

    async def infer_embedding(self, req) -> EmbeddingInferenceResponse:
        self.embedding_calls.append(req)
        return EmbeddingInferenceResponse(
            inference_id="integ-e1",
            provider_id="p-mock",
            model_id="emb-mock",
            embeddings=[[0.25, 0.75]],
            dimensions=2,
        )

    async def stream_chat(self, req: ChatInferenceRequest) -> AsyncIterator[str]:
        self.stream_calls.append(req)
        yield "mock-"
        yield "stream"


@pytest.fixture()
async def inference_mock_client(
    _integration_env: None,
) -> AsyncIterator[tuple[AsyncClient, _RecordingMockProviderService]]:
    """ASGI client with ProviderService dependency overridden by a mock."""
    import syndicateclaw.api.main as main_mod

    importlib.reload(main_mod)

    mock_svc = _RecordingMockProviderService()
    app = main_mod.create_app()
    app.dependency_overrides[get_provider_service] = lambda: mock_svc

    try:
        async with LifespanManager(app) as manager, AsyncClient(
            transport=ASGITransport(app=manager.app), base_url="http://test"
        ) as ac:
            # Do not gate on /readyz: ProviderService is mocked; we still want
            # HTTP-layer coverage when Postgres/Redis are down (e.g. CI).
            yield ac, mock_svc
    except OSError as exc:
        pytest.skip(f"Integration test infrastructure unavailable: {exc}")
    except Exception as exc:
        if "Connect call failed" in str(exc) or "Connection refused" in str(exc):
            pytest.skip(f"Integration test infrastructure unavailable: {exc}")
        raise
    finally:
        app.dependency_overrides.pop(get_provider_service, None)


class TestInferenceAuthzRegistryAlignment:
    """Route registry keys must match real FastAPI routes (shadow RBAC contract)."""

    def test_inference_paths_registered_for_shadow_rbac(self, _integration_env: None) -> None:
        import syndicateclaw.api.main as main_mod

        importlib.reload(main_mod)
        app = main_mod.create_app()
        registered = _collect_api_route_keys(app)
        missing = INFERENCE_HTTP_ROUTES - registered
        assert not missing, f"FastAPI missing routes: {missing}"

    def test_authz_registry_has_specs_for_inference_routes(
        self, _integration_env: None
    ) -> None:
        for method, path in INFERENCE_HTTP_ROUTES:
            spec = get_route_spec(method, path)
            assert spec is not None, f"ROUTE_UNREGISTERED for {(method, path)}"

    def test_inference_permissions_expected(self, _integration_env: None) -> None:
        chat = get_route_spec("POST", "/api/v1/inference/chat")
        assert chat is not None and chat.permission == "inference:invoke_chat"
        emb = get_route_spec("POST", "/api/v1/inference/embedding")
        assert emb is not None and emb.permission == "inference:invoke_embedding"
        prov = get_route_spec("GET", "/api/v1/providers/")
        assert prov is not None and prov.permission == "provider:read"


class TestInferenceHttpWithMockedService:
    """HTTP behavior when ProviderService is mocked (no external inference)."""

    async def test_post_chat_json_round_trip(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        payload = {
            "messages": [{"role": "user", "content": "hi"}],
            "trace_id": "trace-integration-1",
            "provider_id": "p1",
            "model_id": "m1",
        }
        resp = await client.post("/api/v1/inference/chat", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "mocked-reply"
        assert data["provider_id"] == "p-mock"
        assert len(mock_svc.chat_calls) == 1
        assert mock_svc.chat_calls[0].trace_id == "trace-integration-1"

    async def test_post_embedding_json_round_trip(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        payload = {
            "inputs": ["one", "two"],
            "trace_id": "emb-trace-2",
        }
        resp = await client.post("/api/v1/inference/embedding", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["dimensions"] == 2
        assert data["embeddings"] == [[0.25, 0.75]]
        assert len(mock_svc.embedding_calls) == 1
        assert mock_svc.embedding_calls[0].trace_id == "emb-trace-2"

    async def test_chat_service_error_maps_to_502_with_detail(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        mock_svc.raise_on_chat = RuntimeError("simulated upstream failure")
        resp = await client.post(
            "/api/v1/inference/chat",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 502
        body = resp.json()
        assert "simulated upstream failure" in body.get("detail", "")

    async def test_idempotency_conflict_maps_to_409(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        mock_svc.raise_on_chat = IdempotencyConflictError("hash mismatch")
        resp = await client.post(
            "/api/v1/inference/chat",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 409
        assert "hash mismatch" in resp.json().get("detail", "")

    async def test_stream_chat_media_type_and_body(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        payload = {
            "messages": [{"role": "user", "content": "stream me"}],
            "trace_id": "stream-t1",
        }
        async with client.stream(
            "POST",
            "/api/v1/inference/chat/stream",
            json=payload,
        ) as resp:
            assert resp.status_code == 200
            ctype = resp.headers.get("content-type", "")
            assert "text/plain" in ctype
            assert "utf-8" in ctype
            chunks: list[str] = []
            async for part in resp.aiter_text():
                chunks.append(part)
            body = "".join(chunks)
            assert body == "mock-stream"
        assert len(mock_svc.stream_calls) == 1
        assert mock_svc.stream_calls[0].trace_id == "stream-t1"

    async def test_x_request_id_propagates_to_response_header(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, _ = inference_mock_client
        rid = "custom-req-id-integration"
        resp = await client.post(
            "/api/v1/inference/chat",
            json={"messages": [{"role": "user", "content": "id"}]},
            headers={"X-Request-ID": rid},
        )
        assert resp.status_code == 200
        assert resp.headers.get("X-Request-ID") == rid


class TestInferenceHttpErrorMapping:
    """Pins inference domain exception → HTTP status (see api/inference_http.py)."""

    async def test_inference_denied_maps_to_403(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        mock_svc.raise_on_chat = InferenceDeniedError("policy")
        resp = await client.post(
            "/api/v1/inference/chat",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 403

    async def test_routing_policy_denied_maps_to_403(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        mock_svc.raise_on_chat = InferenceRoutingError(
            "capability_denied",
            failure_reason=RoutingFailureReason.POLICY_DENIED,
        )
        resp = await client.post(
            "/api/v1/inference/chat",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 403

    async def test_routing_pin_mismatch_maps_to_400(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        mock_svc.raise_on_chat = InferenceRoutingError(
            "pin",
            failure_reason=RoutingFailureReason.PIN_MISMATCH,
        )
        resp = await client.post(
            "/api/v1/inference/chat",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 400

    async def test_routing_no_candidates_maps_to_503(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        mock_svc.raise_on_chat = InferenceRoutingError(
            "none",
            failure_reason=RoutingFailureReason.NO_CANDIDATES,
        )
        resp = await client.post(
            "/api/v1/inference/chat",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 503

    async def test_execution_provider_maps_to_503(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        mock_svc.raise_on_chat = InferenceExecutionError(
            "all_candidates_failed",
            category=ErrorCategory.PROVIDER,
            retryable=False,
        )
        resp = await client.post(
            "/api/v1/inference/chat",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 503

    async def test_execution_timeout_maps_to_503(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        mock_svc.raise_on_chat = InferenceExecutionError(
            "global_latency_cap_exceeded",
            category=ErrorCategory.TIMEOUT,
            retryable=False,
        )
        resp = await client.post(
            "/api/v1/inference/chat",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 503

    async def test_validation_maps_to_422(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        mock_svc.raise_on_chat = InferenceValidationError("bad input")
        resp = await client.post(
            "/api/v1/inference/chat",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 422

    async def test_approval_required_maps_to_409(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client
        mock_svc.raise_on_chat = InferenceApprovalRequiredError("pending approval")
        resp = await client.post(
            "/api/v1/inference/chat",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 409

    async def test_stream_preflight_routing_error_maps_to_status(
        self, inference_mock_client: tuple[AsyncClient, _RecordingMockProviderService]
    ) -> None:
        client, mock_svc = inference_mock_client

        async def fail_before_yield(_req: ChatInferenceRequest) -> AsyncIterator[str]:
            raise InferenceRoutingError(
                "no_routes",
                failure_reason=RoutingFailureReason.NO_CANDIDATES,
            )
            yield ""  # pragma: no cover

        mock_svc.stream_chat = fail_before_yield  # type: ignore[method-assign]
        resp = await client.post(
            "/api/v1/inference/chat/stream",
            json={"messages": [{"role": "user", "content": "x"}]},
        )
        assert resp.status_code == 503


class TestInferenceOpenApiSurface:
    """OpenAPI lists inference paths (contract visibility for clients)."""

    async def test_openapi_contains_inference_paths(
        self, integration_app_client: AsyncClient
    ) -> None:
        resp = await integration_app_client.get("/openapi.json")
        assert resp.status_code == 200
        paths = resp.json().get("paths", {})
        for _, path in INFERENCE_HTTP_ROUTES:
            assert path in paths, f"missing OpenAPI path {path}"
