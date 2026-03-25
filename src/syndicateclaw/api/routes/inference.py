"""Inference API — Gate 1 absent; Gates 2–4 enforced inside ProviderService."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError

from syndicateclaw.api.dependencies import get_current_actor, get_provider_service
from syndicateclaw.api.inference_http import inference_error_to_http
from syndicateclaw.inference.errors import InferenceError
from syndicateclaw.inference.types import (
    ChatInferenceRequest,
    ChatMessage,
    DataSensitivity,
    EmbeddingInferenceRequest,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/inference", tags=["inference"])


class ChatApiRequest(BaseModel):
    messages: list[dict[str, Any]]
    trace_id: str | None = None
    idempotency_key: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    sensitivity: str = DataSensitivity.INTERNAL.value
    scope_type: str = "PLATFORM"
    scope_id: str = "default"
    temperature: float | None = None
    max_tokens: int | None = None


class EmbeddingApiRequest(BaseModel):
    inputs: list[str]
    trace_id: str | None = None
    idempotency_key: str | None = None
    provider_id: str | None = None
    model_id: str | None = None
    scope_type: str = "PLATFORM"
    scope_id: str = "default"


@router.post("/chat")
async def inference_chat(
    body: ChatApiRequest,
    actor: str = Depends(get_current_actor),  # noqa: B008
    svc: Any = Depends(get_provider_service),  # noqa: B008
) -> dict[str, Any]:
    try:
        req = ChatInferenceRequest(
            messages=[ChatMessage(**m) for m in body.messages],
            actor=actor,
            trace_id=body.trace_id or "",
            idempotency_key=body.idempotency_key,
            provider_id=body.provider_id,
            model_id=body.model_id,
            sensitivity=DataSensitivity(body.sensitivity),
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
        out = await svc.infer_chat(req)
        return out.model_dump(mode="json")
    except ValidationError as exc:
        raise inference_error_to_http(exc) from exc
    except InferenceError as exc:
        raise inference_error_to_http(exc) from exc
    except Exception as exc:
        logger.exception("inference.chat_failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/embedding")
async def inference_embedding(
    body: EmbeddingApiRequest,
    actor: str = Depends(get_current_actor),  # noqa: B008
    svc: Any = Depends(get_provider_service),  # noqa: B008
) -> dict[str, Any]:
    try:
        req = EmbeddingInferenceRequest(
            inputs=body.inputs,
            actor=actor,
            trace_id=body.trace_id or "",
            idempotency_key=body.idempotency_key,
            provider_id=body.provider_id,
            model_id=body.model_id,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
        )
        out = await svc.infer_embedding(req)
        return out.model_dump(mode="json")
    except ValidationError as exc:
        raise inference_error_to_http(exc) from exc
    except InferenceError as exc:
        raise inference_error_to_http(exc) from exc
    except Exception as exc:
        logger.exception("inference.embedding_failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/chat/stream", response_model=None)
async def inference_chat_stream(
    body: ChatApiRequest,
    actor: str = Depends(get_current_actor),  # noqa: B008
    svc: Any = Depends(get_provider_service),  # noqa: B008
) -> StreamingResponse | Response:
    """Streaming: no idempotency in Phase 1.

    First-chunk errors are preflighted so status codes are not committed as 200 first.
    """

    try:
        req = ChatInferenceRequest(
            messages=[ChatMessage(**m) for m in body.messages],
            actor=actor,
            trace_id=body.trace_id or "",
            provider_id=body.provider_id,
            model_id=body.model_id,
            sensitivity=DataSensitivity(body.sensitivity),
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
        )
    except ValidationError as exc:
        raise inference_error_to_http(exc) from exc

    it = svc.stream_chat(req)
    try:
        first = await it.__anext__()
    except StopAsyncIteration:
        return Response(status_code=204)
    except InferenceError as exc:
        raise inference_error_to_http(exc) from exc

    async def gen() -> Any:
        yield first
        try:
            async for chunk in it:
                yield chunk
        except Exception:
            logger.exception("inference.stream_failed")
            raise

    return StreamingResponse(gen(), media_type="text/plain; charset=utf-8")
