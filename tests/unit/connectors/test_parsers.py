from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from syndicateclaw.connectors.base import ConnectorMessage, Platform
from syndicateclaw.connectors.discord.bot import (
    APPLICATION_COMMAND,
    INTERACTION_TYPE_PING,
    DiscordConnector,
)
from syndicateclaw.connectors.slack.bot import SlackConnector
from syndicateclaw.connectors.telegram.bot import TelegramConnector, _parse_command


class TestParseCommand:
    def test_plain_text_not_command(self) -> None:
        assert _parse_command("hello world") == (False, None, None)

    def test_help_command_without_args(self) -> None:
        assert _parse_command("/help") == (True, "/help", None)

    def test_run_command_with_args(self) -> None:
        assert _parse_command("/run workflow-alpha") == (True, "/run", "workflow-alpha")

    def test_command_strips_bot_mention(self) -> None:
        assert _parse_command("/start@MyBot") == (True, "/start", None)

    def test_whitespace_not_command(self) -> None:
        assert _parse_command("   ") == (False, None, None)


class TestTelegramParseUpdate:
    @staticmethod
    def _connector() -> TelegramConnector:
        settings = SimpleNamespace(
            telegram_bot_token="token",
            telegram_webhook_secret="secret",
            public_base_url="https://example.com",
        )
        return TelegramConnector(MagicMock(), settings)

    def test_plain_message_fields(self) -> None:
        connector = self._connector()
        message = connector.parse_update(
            {
                "message": {
                    "message_id": 111,
                    "text": "hello",
                    "chat": {"id": 999},
                    "from": {"id": 42},
                }
            }
        )
        assert message is not None
        assert message.platform_message_id == "111"
        assert message.channel_id == "999"
        assert message.user_id == "42"
        assert message.text == "hello"

    def test_command_detection(self) -> None:
        connector = self._connector()
        message = connector.parse_update(
            {
                "message": {
                    "message_id": 1,
                    "text": "/run nightly",
                    "chat": {"id": 2},
                    "from": {"id": 3},
                }
            }
        )
        assert message is not None
        assert message.is_command is True
        assert message.command == "/run"
        assert message.command_args == "nightly"

    def test_non_message_returns_none(self) -> None:
        connector = self._connector()
        assert connector.parse_update({"callback_query": {"id": "x"}}) is None

    def test_empty_text_returns_none(self) -> None:
        connector = self._connector()
        assert (
            connector.parse_update(
                {
                    "message": {
                        "message_id": 1,
                        "text": "",
                        "chat": {"id": 2},
                        "from": {"id": 3},
                    }
                }
            )
            is None
        )

    def test_actor_format(self) -> None:
        connector = self._connector()
        message = connector.parse_update(
            {
                "message": {
                    "message_id": 10,
                    "text": "hey",
                    "chat": {"id": 20},
                    "from": {"id": 30},
                }
            }
        )
        assert message is not None
        assert message.actor == "connector:telegram:30"

    def test_memory_namespace_format(self) -> None:
        connector = self._connector()
        message = connector.parse_update(
            {
                "message": {
                    "message_id": 10,
                    "text": "hey",
                    "chat": {"id": 20},
                    "from": {"id": 30},
                }
            }
        )
        assert message is not None
        assert message.memory_namespace == "connector:telegram:20"

    def test_edited_message_is_accepted(self) -> None:
        connector = self._connector()
        message = connector.parse_update(
            {
                "edited_message": {
                    "message_id": 7,
                    "text": "updated",
                    "chat": {"id": 8},
                    "from": {"id": 9},
                }
            }
        )
        assert message is not None
        assert message.text == "updated"

    def test_platform_is_telegram(self) -> None:
        connector = self._connector()
        message = connector.parse_update(
            {
                "message": {
                    "message_id": 10,
                    "text": "hey",
                    "chat": {"id": 20},
                    "from": {"id": 30},
                }
            }
        )
        assert message is not None
        assert message.platform is Platform.TELEGRAM


class TestDiscordParseInteraction:
    @staticmethod
    def _connector() -> DiscordConnector:
        settings = SimpleNamespace(
            discord_bot_token="token",
            discord_app_id="app-id",
            discord_public_key="",
            discord_guild_ids="",
        )
        return DiscordConnector(MagicMock(), settings)

    def test_chat_is_not_command(self) -> None:
        connector = self._connector()
        msg = connector.parse_interaction(
            {
                "type": APPLICATION_COMMAND,
                "id": "i-1",
                "token": "tok-1",
                "channel_id": "c-1",
                "member": {"user": {"id": "u-1"}},
                "data": {
                    "name": "chat",
                    "options": [{"name": "message", "value": "hello from discord"}],
                },
            }
        )
        assert msg is not None
        assert msg.is_command is False
        assert msg.text == "hello from discord"

    def test_run_is_command_with_workflow_arg(self) -> None:
        connector = self._connector()
        msg = connector.parse_interaction(
            {
                "type": APPLICATION_COMMAND,
                "id": "i-2",
                "token": "tok-2",
                "channel_id": "c-2",
                "member": {"user": {"id": "u-2"}},
                "data": {
                    "name": "run",
                    "options": [{"name": "workflow", "value": "daily-sync"}],
                },
            }
        )
        assert msg is not None
        assert msg.is_command is True
        assert msg.command == "/run"
        assert msg.command_args == "daily-sync"

    def test_followup_token_is_stored(self) -> None:
        connector = self._connector()
        connector.parse_interaction(
            {
                "type": APPLICATION_COMMAND,
                "id": "i-3",
                "token": "tok-3",
                "channel_id": "c-3",
                "member": {"user": {"id": "u-3"}},
                "data": {
                    "name": "status",
                },
            }
        )
        assert connector._followup_tokens["i-3"] == "tok-3"

    def test_status_is_command(self) -> None:
        connector = self._connector()
        msg = connector.parse_interaction(
            {
                "type": APPLICATION_COMMAND,
                "id": "i-4",
                "token": "tok-4",
                "channel_id": "c-4",
                "member": {"user": {"id": "u-4"}},
                "data": {
                    "name": "status",
                },
            }
        )
        assert msg is not None
        assert msg.is_command is True
        assert msg.command == "/status"

    def test_ping_returns_none(self) -> None:
        connector = self._connector()
        assert connector.parse_interaction({"type": INTERACTION_TYPE_PING}) is None

    def test_component_returns_none(self) -> None:
        connector = self._connector()
        assert connector.parse_interaction({"type": 3}) is None

    def test_platform_is_discord(self) -> None:
        connector = self._connector()
        msg = connector.parse_interaction(
            {
                "type": APPLICATION_COMMAND,
                "id": "i-5",
                "token": "tok-5",
                "channel_id": "c-5",
                "member": {"user": {"id": "u-5"}},
                "data": {
                    "name": "help",
                },
            }
        )
        assert msg is not None
        assert msg.platform is Platform.DISCORD


class TestSlackParseEvent:
    @staticmethod
    def _connector() -> SlackConnector:
        settings = SimpleNamespace(
            slack_bot_token="xoxb-test",
            slack_signing_secret="sign-secret",
        )
        return SlackConnector(MagicMock(), settings)

    def test_app_mention_strips_mention_prefix(self) -> None:
        connector = self._connector()
        msg = connector.parse_event(
            {
                "event": {
                    "type": "app_mention",
                    "text": "<@UAPP> hello there",
                    "channel": "C123",
                    "user": "U123",
                    "ts": "171234.0001",
                }
            }
        )
        assert msg is not None
        assert msg.text == "hello there"

    def test_direct_message_parses(self) -> None:
        connector = self._connector()
        msg = connector.parse_event(
            {
                "event": {
                    "type": "message",
                    "text": "dm ping",
                    "channel": "D123",
                    "user": "U123",
                    "ts": "171234.0002",
                }
            }
        )
        assert msg is not None
        assert msg.channel_id == "D123"

    def test_bot_id_event_returns_none(self) -> None:
        connector = self._connector()
        assert (
            connector.parse_event(
                {
                    "event": {
                        "type": "message",
                        "text": "hello",
                        "channel": "C1",
                        "bot_id": "B1",
                        "user": "U1",
                        "ts": "171234.0003",
                    }
                }
            )
            is None
        )

    def test_command_message_parsed(self) -> None:
        connector = self._connector()
        msg = connector.parse_event(
            {
                "event": {
                    "type": "message",
                    "text": "/status",
                    "channel": "C1",
                    "user": "U1",
                    "ts": "171234.0004",
                }
            }
        )
        assert msg is not None
        assert msg.is_command is True
        assert msg.command == "/status"

    def test_empty_text_returns_none(self) -> None:
        connector = self._connector()
        assert (
            connector.parse_event(
                {
                    "event": {
                        "type": "message",
                        "text": "",
                        "channel": "C1",
                        "user": "U1",
                        "ts": "171234.0005",
                    }
                }
            )
            is None
        )

    def test_non_message_event_returns_none(self) -> None:
        connector = self._connector()
        assert connector.parse_event({"event": {"type": "reaction_added"}}) is None

    def test_platform_is_slack(self) -> None:
        connector = self._connector()
        msg = connector.parse_event(
            {
                "event": {
                    "type": "message",
                    "text": "hello",
                    "channel": "C1",
                    "user": "U1",
                    "ts": "171234.0006",
                }
            }
        )
        assert msg is not None
        assert msg.platform is Platform.SLACK

    def test_thread_ts_captured(self) -> None:
        connector = self._connector()
        msg = connector.parse_event(
            {
                "event": {
                    "type": "message",
                    "text": "thread reply",
                    "channel": "C1",
                    "user": "U1",
                    "ts": "171234.0007",
                    "thread_ts": "171200.1000",
                }
            }
        )
        assert msg is not None
        assert msg.thread_id == "171200.1000"


class TestSlackParseSlashCommand:
    @staticmethod
    def _connector() -> SlackConnector:
        settings = SimpleNamespace(
            slack_bot_token="xoxb-test",
            slack_signing_secret="sign-secret",
        )
        return SlackConnector(MagicMock(), settings)

    def test_basic_form_fields(self) -> None:
        connector = self._connector()
        msg = connector.parse_slash_command(
            {
                "command": "/run",
                "text": "nightly",
                "channel_id": "C123",
                "user_id": "U123",
                "trigger_id": "1337.42",
            }
        )
        assert msg.command == "/run"
        assert msg.command_args == "nightly"
        assert msg.channel_id == "C123"

    def test_empty_text_has_no_command_args(self) -> None:
        connector = self._connector()
        msg = connector.parse_slash_command(
            {
                "command": "/status",
                "text": "",
                "channel_id": "C123",
                "user_id": "U123",
                "trigger_id": "1337.43",
            }
        )
        assert msg.command == "/status"
        assert msg.command_args is None


class TestConnectorMessageProperties:
    @pytest.mark.parametrize(
        ("platform", "user", "channel", "expected_actor", "expected_ns"),
        [
            (
                Platform.TELEGRAM,
                "u-telegram",
                "c-telegram",
                "connector:telegram:u-telegram",
                "connector:telegram:c-telegram",
            ),
            (
                Platform.DISCORD,
                "u-discord",
                "c-discord",
                "connector:discord:u-discord",
                "connector:discord:c-discord",
            ),
            (
                Platform.SLACK,
                "u-slack",
                "c-slack",
                "connector:slack:u-slack",
                "connector:slack:c-slack",
            ),
        ],
    )
    def test_actor_and_memory_namespace(
        self,
        platform: Platform,
        user: str,
        channel: str,
        expected_actor: str,
        expected_ns: str,
    ) -> None:
        msg = ConnectorMessage(
            platform=platform,
            platform_message_id="msg-1",
            channel_id=channel,
            user_id=user,
            text="hi",
            raw={},
        )
        assert msg.actor == expected_actor
        assert msg.memory_namespace == expected_ns
