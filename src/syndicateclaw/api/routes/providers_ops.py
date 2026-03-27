"""Provider list from YAML-backed loader (read-only topology) and catalog sync."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from syndicateclaw.api.dependencies import (
    get_audit_service,
    get_current_actor,
    get_inference_catalog,
    get_provider_loader,
    get_settings,
)
from syndicateclaw.config import Settings
from syndicateclaw.inference.adapters.factory import adapter_for
from syndicateclaw.inference.catalog_sync.modelsdev import ModelsDevSyncResult
from syndicateclaw.inference.catalog_sync.runner import run_models_dev_catalog_sync
from syndicateclaw.inference.service import _resolve_auth
from syndicateclaw.inference.types import ChatInferenceRequest, ChatMessage

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


class SyncModelsDevRequest(BaseModel):
    """Optional override; when omitted, ``Settings.models_dev_feed_url`` is used."""

    feed_url: str | None = Field(
        default=None,
        description="HTTPS URL for models.dev-style JSON (must pass SSRF policy).",
    )


def _http_status_for_sync_result(result: ModelsDevSyncResult) -> int:
    if result.applied:
        return 200
    reason = result.aborted_reason
    if reason == "ssrf_blocked":
        return 403
    if reason == "parse_failed":
        return 422
    if reason in ("fetch_failed", "systemic_anomaly_drop"):
        return 503
    return 500


@router.get("/")
async def list_providers(
    actor: str = Depends(get_current_actor),  # noqa: B008
    loader: Any = Depends(get_provider_loader),  # noqa: B008
) -> dict[str, Any]:
    _ = actor
    try:
        cfg, ver = loader.current()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="provider config not loaded") from None
    return {
        "system_config_version": ver,
        "inference_enabled": cfg.inference_enabled,
        "providers": [p.model_dump(mode="json") for p in cfg.providers],
    }


@router.post("/catalog/sync-models-dev")
async def sync_models_dev_catalog(
    body: SyncModelsDevRequest,
    actor: str = Depends(get_current_actor),  # noqa: B008
    settings: Settings = Depends(get_settings),  # noqa: B008
    loader: Any = Depends(get_provider_loader),  # noqa: B008
    catalog: Any = Depends(get_inference_catalog),  # noqa: B008
    audit_service: Any = Depends(get_audit_service),  # noqa: B008
) -> JSONResponse:
    """Fetch models.dev JSON (SSRF-safe), parse, merge into catalog; YAML stays authoritative."""
    feed = (body.feed_url or "").strip() or settings.models_dev_feed_url
    if not feed:
        raise HTTPException(
            status_code=503,
            detail=(
                "models.dev feed URL is not configured "
                "(set SYNDICATECLAW_MODELS_DEV_FEED_URL or pass feed_url)"
            ),
        )

    try:
        base_cfg, _ver = loader.current()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="provider config not loaded") from None

    try:
        result = await run_models_dev_catalog_sync(
            feed_url=feed,
            allowed_host_suffixes=tuple(settings.models_dev_allowed_host_suffixes),
            max_bytes=settings.models_dev_max_fetch_bytes,
            timeout_seconds=settings.models_dev_fetch_timeout_seconds,
            max_redirects=settings.models_dev_max_redirects,
            catalog=catalog,
            base_system_config=base_cfg,
            audit_service=audit_service,
            actor=actor,
        )
    except Exception as exc:
        logger.exception("providers.sync_models_dev_unexpected")
        raise HTTPException(status_code=500, detail="catalog sync failed") from exc

    status_code = _http_status_for_sync_result(result)
    return JSONResponse(
        status_code=status_code,
        content=result.model_dump(mode="json"),
    )


@router.post("/{name}/test", response_model=None)
async def test_provider_connectivity(
    name: str,
    actor: str = Depends(get_current_actor),  # noqa: B008
    loader: Any = Depends(get_provider_loader),  # noqa: B008
) -> Any:
    _ = actor
    try:
        cfg, _ver = loader.current()
        provider = next((p for p in cfg.providers if p.name == name or p.id == name), None)
        if provider is None:
            return JSONResponse({"status": "unreachable", "provider": name}, status_code=502)
        adapter = adapter_for(provider.adapter_protocol)
        api_key, _api_key_secondary = _resolve_auth(provider)
        req = ChatInferenceRequest(
            messages=[ChatMessage(role="user", content="ping")],
            actor=actor,
            trace_id="provider-test",
            model_id=(provider.allowed_models[0] if provider.allowed_models else None),
            provider_id=provider.id,
        )
        await adapter.infer_chat(provider, req, api_key=api_key, bearer_token=None)
        return {"status": "ok", "provider": name}
    except Exception:
        return JSONResponse(
            {"status": "unreachable", "provider": name},
            status_code=502,
        )
