from __future__ import annotations

from typing import Any

import structlog

from syndicateclaw.connectors.base import ConnectorBase, ConnectorStatus, Platform
from syndicateclaw.connectors.discord.bot import DiscordConnector
from syndicateclaw.connectors.slack.bot import SlackConnector
from syndicateclaw.connectors.telegram.bot import TelegramConnector

logger = structlog.get_logger(__name__)


class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[Platform, ConnectorBase] = {}

    def register(self, connector: ConnectorBase) -> None:
        self._connectors[connector.platform] = connector

    def get(self, platform: Platform) -> ConnectorBase | None:
        return self._connectors.get(platform)

    def all(self) -> list[ConnectorBase]:
        return list(self._connectors.values())

    def statuses(self) -> list[ConnectorStatus]:
        return [connector.status for connector in self._connectors.values()]

    async def start_all(self) -> None:
        for connector in self._connectors.values():
            try:
                await connector.start()
                logger.info("connector.started", platform=connector.platform.value)
            except Exception:
                logger.exception("connector.start_failed", platform=connector.platform.value)

    async def stop_all(self) -> None:
        for connector in self._connectors.values():
            try:
                await connector.stop()
                logger.info("connector.stopped", platform=connector.platform.value)
            except Exception:
                logger.exception("connector.stop_failed", platform=connector.platform.value)


def build_registry(settings: Any, provider_service: Any) -> ConnectorRegistry:
    registry = ConnectorRegistry()

    if getattr(settings, "telegram_bot_token", None):
        registry.register(TelegramConnector(provider_service, settings))

    if getattr(settings, "discord_bot_token", None):
        registry.register(DiscordConnector(provider_service, settings))

    if getattr(settings, "slack_bot_token", None) and getattr(settings, "slack_signing_secret", None):
        registry.register(SlackConnector(provider_service, settings))

    return registry
