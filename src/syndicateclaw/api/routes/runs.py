from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from syndicateclaw.api.dependencies import get_current_actor, get_streaming_token_service

router = APIRouter(prefix="/api/v1/runs", tags=["runs"])

DEP_CURRENT_ACTOR = Depends(get_current_actor)
DEP_STREAMING_TOKEN_SERVICE = Depends(get_streaming_token_service)


@router.post("/{run_id}/streaming-token")
async def issue_streaming_token(
    run_id: str,
    actor: str = DEP_CURRENT_ACTOR,
    streaming_token_service: Any = DEP_STREAMING_TOKEN_SERVICE,
) -> dict[str, str]:
    token = await streaming_token_service.issue(run_id=run_id, actor=actor)
    return {
        "streaming_token": token.token,
        "expires_at": token.expires_at.isoformat(),
    }
