from __future__ import annotations

import asyncio
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


async def expire_stale_agents(agent_service: Any) -> int:
    """Transition ONLINE agents with stale heartbeats to OFFLINE."""
    return int(await agent_service.transition_stale_to_offline())


async def run_agent_heartbeat_expiry_loop(agent_service: Any, *, interval_seconds: int) -> None:
    """Poll for stale heartbeats and transition stale ONLINE agents to OFFLINE."""
    while True:
        try:
            transitioned = await expire_stale_agents(agent_service)
            if transitioned:
                logger.info("agents.heartbeat_expired", transitioned=transitioned)
        except Exception:
            logger.warning("agents.heartbeat_expiry_failed", exc_info=True)
        await asyncio.sleep(interval_seconds)
