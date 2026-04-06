"""Chat connector integrations for external platforms."""

from syndicateclaw.connectors.base import (
    ConnectorBase,
    ConnectorMessage,
    ConnectorStatus,
    Platform,
)
from syndicateclaw.connectors.discord.bot import DiscordConnector
from syndicateclaw.connectors.registry import ConnectorRegistry, build_registry
from syndicateclaw.connectors.slack.bot import SlackConnector
from syndicateclaw.connectors.telegram.bot import TelegramConnector

__all__ = [
    "ConnectorBase",
    "ConnectorMessage",
    "ConnectorRegistry",
    "ConnectorStatus",
    "DiscordConnector",
    "Platform",
    "SlackConnector",
    "TelegramConnector",
    "build_registry",
]
