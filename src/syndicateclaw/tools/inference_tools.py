"""Buffered llm_inference / embedding_inference tools — delegate to ProviderService only."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from syndicateclaw.models import Tool, ToolRiskLevel

if TYPE_CHECKING:
    from syndicateclaw.inference.service import ProviderService

from syndicateclaw.inference.types import (
    ChatInferenceRequest,
    ChatMessage,
    EmbeddingInferenceRequest,
)


def build_inference_tools(provider_service: ProviderService) -> list[tuple[Tool, Any]]:
    """Register tools that call infer_chat / infer_embedding (never stream_chat)."""

    llm_tool = Tool(
        name="llm_inference",
        description="Buffered chat completion via ProviderService (no streaming).",
        version="1.0.0",
        risk_level=ToolRiskLevel.HIGH,
        input_schema={
            "type": "object",
            "required": ["messages", "actor"],
            "properties": {
                "messages": {"type": "array"},
                "actor": {"type": "string"},
                "trace_id": {"type": "string"},
                "provider_id": {"type": "string"},
                "model_id": {"type": "string"},
                "sensitivity": {"type": "string"},
                "scope_type": {"type": "string"},
                "scope_id": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "inference_id": {"type": "string"},
                "content": {"type": "string"},
                "provider_id": {"type": "string"},
                "model_id": {"type": "string"},
            },
        },
        idempotent=False,
        timeout_seconds=180,
        owner="syndicateclaw",
    )

    embed_tool = Tool(
        name="embedding_inference",
        description="Buffered embeddings via ProviderService.",
        version="1.0.0",
        risk_level=ToolRiskLevel.MEDIUM,
        input_schema={
            "type": "object",
            "required": ["inputs", "actor"],
            "properties": {
                "inputs": {"type": "array", "items": {"type": "string"}},
                "actor": {"type": "string"},
                "trace_id": {"type": "string"},
                "provider_id": {"type": "string"},
                "model_id": {"type": "string"},
                "scope_type": {"type": "string"},
                "scope_id": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "inference_id": {"type": "string"},
                "dimensions": {"type": "integer"},
                "provider_id": {"type": "string"},
                "model_id": {"type": "string"},
            },
        },
        idempotent=True,
        timeout_seconds=120,
        owner="syndicateclaw",
    )

    async def llm_handler(input_data: dict[str, Any]) -> dict[str, Any]:
        msgs = [ChatMessage(**m) for m in input_data["messages"]]
        req = ChatInferenceRequest(
            messages=msgs,
            actor=input_data["actor"],
            trace_id=input_data.get("trace_id") or "",
            provider_id=input_data.get("provider_id"),
            model_id=input_data.get("model_id"),
            scope_type=input_data.get("scope_type", "PLATFORM"),
            scope_id=input_data.get("scope_id", "default"),
        )
        out = await provider_service.infer_chat(req)
        return out.model_dump(mode="json")

    async def embed_handler(input_data: dict[str, Any]) -> dict[str, Any]:
        req = EmbeddingInferenceRequest(
            inputs=list(input_data["inputs"]),
            actor=input_data["actor"],
            trace_id=input_data.get("trace_id") or "",
            provider_id=input_data.get("provider_id"),
            model_id=input_data.get("model_id"),
            scope_type=input_data.get("scope_type", "PLATFORM"),
            scope_id=input_data.get("scope_id", "default"),
        )
        out = await provider_service.infer_embedding(req)
        return out.model_dump(mode="json")

    return [(llm_tool, llm_handler), (embed_tool, embed_handler)]
