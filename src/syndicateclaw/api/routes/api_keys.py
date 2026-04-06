from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from syndicateclaw.api.dependencies import get_current_actor, get_settings
from syndicateclaw.authz.permissions import PERMISSION_VOCABULARY
from syndicateclaw.config import Settings

router = APIRouter(prefix="/api/v1/api-keys", tags=["api-keys"])

DEP_CURRENT_ACTOR = Depends(get_current_actor)
DEP_SETTINGS = Depends(get_settings)


@router.get("/scopes")
async def list_scopes(
    _actor: str = DEP_CURRENT_ACTOR,
    settings: Settings = DEP_SETTINGS,
) -> dict[str, Any]:
    return {
        "scopes": sorted(PERMISSION_VOCABULARY),
        "unscoped_keys_allowed": settings.allow_unscoped_keys,
    }
