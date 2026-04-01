"""Unit tests for files previously at 0% coverage.

Covers:
- syndicateclaw.channels.console.ConsoleChannel
- syndicateclaw.plugins.builtin.audit_trail.AuditTrailPlugin
- syndicateclaw.plugins.builtin.webhook.WebhookPlugin
- syndicateclaw.tasks.idempotency_cleanup.cleanup_expired_idempotency_rows
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.channels import ChannelMessage
from syndicateclaw.channels.console import ConsoleChannel
from syndicateclaw.plugins.base import PluginContext
from syndicateclaw.plugins.builtin.audit_trail import AuditTrailPlugin
from syndicateclaw.plugins.builtin.webhook import WebhookPlugin
from syndicateclaw.security.ssrf import SSRFError
from syndicateclaw.tasks.idempotency_cleanup import cleanup_expired_idempotency_rows


def _make_ctx(run_id: str = "run-1", workflow_id: str = "wf-1") -> PluginContext:
    return PluginContext(
        run_id=run_id,
        workflow_id=workflow_id,
        actor="test-actor",
        namespace="default",
        state={},
    )


# ---------------------------------------------------------------------------
# ConsoleChannel
# ---------------------------------------------------------------------------


async def test_console_channel_send_returns_true() -> None:
    ch = ConsoleChannel()
    result = await ch.send("hello", recipient="user-1")
    assert result is True


async def test_console_channel_send_with_metadata() -> None:
    ch = ConsoleChannel()
    result = await ch.send("msg", recipient="user-2", metadata={"key": "val"})
    assert result is True


async def test_console_channel_receive_yields_sentinel() -> None:
    ch = ConsoleChannel()
    messages = [msg async for msg in ch.receive()]
    assert len(messages) == 1
    msg = messages[0]
    assert isinstance(msg, ChannelMessage)
    assert msg.channel == "console"
    assert msg.sender == "console"
    assert "no inbound" in msg.content


# ---------------------------------------------------------------------------
# AuditTrailPlugin
# ---------------------------------------------------------------------------


async def test_audit_trail_plugin_on_node_execute_returns_none() -> None:
    plugin = AuditTrailPlugin()
    ctx = _make_ctx()
    result = await plugin.on_node_execute(ctx, node_id="node-1", result={"output": 42})
    assert result is None


async def test_audit_trail_plugin_identity() -> None:
    plugin = AuditTrailPlugin()
    assert plugin.name == "audit_trail"
    assert plugin.version == "1.0.0"


# ---------------------------------------------------------------------------
# WebhookPlugin
# ---------------------------------------------------------------------------


async def test_webhook_plugin_posts_payload_in_dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "development")
    url = "http://localhost:9999/hook"

    mock_response = MagicMock()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    ctx = _make_ctx(run_id="run-abc", workflow_id="wf-xyz")
    plugin = WebhookPlugin(url=url)

    with (
        patch("syndicateclaw.plugins.builtin.webhook.validate_url", return_value=True),
        patch("syndicateclaw.plugins.builtin.webhook.httpx.AsyncClient", return_value=mock_client),
    ):
        await plugin.on_workflow_end(ctx, status="completed")

    mock_client.post.assert_awaited_once()
    _, kwargs = mock_client.post.call_args
    payload = kwargs["json"]
    assert payload["run_id"] == "run-abc"
    assert payload["workflow_id"] == "wf-xyz"
    assert payload["status"] == "completed"


async def test_webhook_plugin_rejects_http_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "production")
    plugin = WebhookPlugin(url="http://example.com/hook")
    ctx = _make_ctx()
    with pytest.raises(SSRFError, match="HTTPS required"):
        await plugin.on_workflow_end(ctx, status="completed")


async def test_webhook_plugin_allows_https_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "production")

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock()

    plugin = WebhookPlugin(url="https://hooks.example.com/notify")
    ctx = _make_ctx()

    with (
        patch("syndicateclaw.plugins.builtin.webhook.validate_url", return_value=True),
        patch("syndicateclaw.plugins.builtin.webhook.httpx.AsyncClient", return_value=mock_client),
    ):
        await plugin.on_workflow_end(ctx, status="failed")

    mock_client.post.assert_awaited_once()


async def test_webhook_plugin_propagates_ssrf_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "development")
    plugin = WebhookPlugin(url="http://169.254.169.254/metadata")
    ctx = _make_ctx()
    with pytest.raises(SSRFError):
        await plugin.on_workflow_end(ctx, status="completed")


# ---------------------------------------------------------------------------
# cleanup_expired_idempotency_rows
# ---------------------------------------------------------------------------


async def test_cleanup_returns_row_count() -> None:
    mock_result = MagicMock()
    mock_result.rowcount = 3

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    mock_factory = MagicMock(return_value=mock_session)

    count = await cleanup_expired_idempotency_rows(mock_factory, ttl_seconds=3600)
    assert count == 3


async def test_cleanup_returns_zero_when_rowcount_none() -> None:
    mock_result = MagicMock()
    mock_result.rowcount = None

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_begin = AsyncMock()
    mock_begin.__aenter__ = AsyncMock(return_value=None)
    mock_begin.__aexit__ = AsyncMock(return_value=False)
    mock_session.begin = MagicMock(return_value=mock_begin)

    mock_factory = MagicMock(return_value=mock_session)

    count = await cleanup_expired_idempotency_rows(mock_factory, ttl_seconds=60)
    assert count == 0
