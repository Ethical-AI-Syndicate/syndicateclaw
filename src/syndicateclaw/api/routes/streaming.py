from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from syndicateclaw.api.dependencies import get_streaming_token_service
from syndicateclaw.services.streaming_token_service import InvalidTokenError
from syndicateclaw.streaming.connection_manager import connection_manager

router = APIRouter(prefix="/api/v1/runs", tags=["streaming"])

DEP_STREAMING_TOKEN_SERVICE = Depends(get_streaming_token_service)


def _sanitize_event(event: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("type", "message"))
    if event_type != "llm_complete":
        return event
    return {
        "type": "llm_complete",
        "usage": event.get("usage", {}),
        "timestamp": event.get("timestamp") or datetime.now(UTC).isoformat(),
    }


@router.get("/{run_id}/stream")
async def stream_run(
    run_id: str,
    token: str = Query(...),
    streaming_token_service: Any = DEP_STREAMING_TOKEN_SERVICE,
) -> StreamingResponse:
    try:
        _actor = await streaming_token_service.validate_and_consume(token, run_id)
    except InvalidTokenError as err:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(err),
        ) from err

    queue = await connection_manager.subscribe(run_id)

    async def event_generator() -> Any:
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                except TimeoutError:
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                safe_event = _sanitize_event(event)
                event_type = str(safe_event.get("type", "message"))
                yield f"event: {event_type}\ndata: {json.dumps(safe_event)}\n\n"
                if event_type == "run_complete":
                    break
        finally:
            await connection_manager.unsubscribe(run_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
