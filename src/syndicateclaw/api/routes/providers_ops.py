"""Provider list from YAML-backed loader (read-only topology)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from syndicateclaw.api.dependencies import get_current_actor, get_provider_loader

router = APIRouter(prefix="/api/v1/providers", tags=["providers"])


@router.get("/")
async def list_providers(
    actor: str = Depends(get_current_actor),  # noqa: B008
    loader=Depends(get_provider_loader),  # noqa: B008
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
