"""Unit tests for plugins, channels, and builder token service.

Covers:
- plugins/security.py
- plugins/executor.py
- plugins/registry.py
- channels/webhook.py
- services/builder_token_service.py
- tasks/org_cleanup.py
"""

from __future__ import annotations

import importlib.util
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from syndicateclaw.models import AuditEventType
from syndicateclaw.plugins.base import Plugin, PluginContext
from syndicateclaw.plugins.executor import PluginExecutor
from syndicateclaw.plugins.registry import PluginConfigError, PluginRegistry
from syndicateclaw.plugins.security import (
    PluginSecurityViolationError,
    check_plugin_security,
)
from syndicateclaw.services.builder_token_service import BuilderTokenService
from syndicateclaw.services.streaming_token_service import InvalidTokenError


def _make_ctx() -> PluginContext:
    return PluginContext(
        run_id="run-1",
        workflow_id="wf-1",
        actor="test",
        namespace="default",
        state={},
    )


def _load_plugin_class_from_source(tmp_path: Path, src: str, class_name: str) -> type:
    """Write src to a temp file and load the named class from it."""
    import sys

    mod_name = class_name.lower()
    mod_file = tmp_path / f"{mod_name}.py"
    mod_file.write_text(src)
    spec = importlib.util.spec_from_file_location(mod_name, mod_file)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod  # register so inspect.getsource can find it
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return getattr(mod, class_name)


# ---------------------------------------------------------------------------
# plugins/security.py
# ---------------------------------------------------------------------------


class _CleanPlugin(Plugin):
    name = "clean"

    async def on_workflow_start(self, ctx: PluginContext) -> None:
        return None


def test_check_plugin_security_passes_clean_plugin() -> None:
    check_plugin_security(_CleanPlugin)  # should not raise


def test_check_plugin_security_rejects_banned_call(tmp_path: Path) -> None:
    src = textwrap.dedent("""\
        from syndicateclaw.plugins.base import Plugin, PluginContext
        class BannedCallPlugin(Plugin):
            name = 'bad'
            async def on_workflow_start(self, ctx: PluginContext) -> None:
                x = compile('1+1', '<string>', 'exec')
    """)
    cls = _load_plugin_class_from_source(tmp_path, src, "BannedCallPlugin")
    with pytest.raises(PluginSecurityViolationError, match="Banned call: compile"):
        check_plugin_security(cls)


def test_check_plugin_security_rejects_banned_import(tmp_path: Path) -> None:
    # Import must be inside the class body so inspect.getsource picks it up
    src = textwrap.dedent("""\
        from syndicateclaw.plugins.base import Plugin, PluginContext
        class ThrPlugin(Plugin):
            name = 'thr'
            async def on_workflow_start(self, ctx: PluginContext) -> None:
                import threading  # noqa: F401
    """)
    cls = _load_plugin_class_from_source(tmp_path, src, "ThrPlugin")
    with pytest.raises(PluginSecurityViolationError, match="Banned import"):
        check_plugin_security(cls)


def test_check_plugin_security_rejects_banned_from_import(tmp_path: Path) -> None:
    src = textwrap.dedent("""\
        from syndicateclaw.plugins.base import Plugin, PluginContext
        class SubPlugin(Plugin):
            name = 'sub'
            async def on_workflow_start(self, ctx: PluginContext) -> None:
                from subprocess import run  # noqa: F401
    """)
    cls = _load_plugin_class_from_source(tmp_path, src, "SubPlugin")
    with pytest.raises(PluginSecurityViolationError, match="Banned import"):
        check_plugin_security(cls)


def test_check_plugin_security_source_unavailable() -> None:
    """When inspect.getsource raises OSError, wrap in PluginSecurityViolationError."""
    import inspect

    with patch.object(inspect, "getsource", side_effect=OSError("no source")), pytest.raises(
        PluginSecurityViolationError, match="Cannot read source"
    ):
        check_plugin_security(_CleanPlugin)


# ---------------------------------------------------------------------------
# plugins/executor.py
# ---------------------------------------------------------------------------


async def test_plugin_executor_successful_hook_emits_events() -> None:
    plugin = _CleanPlugin()
    audit = AsyncMock()
    audit.emit = AsyncMock()
    executor = PluginExecutor([plugin], audit_service=audit)
    ctx = _make_ctx()
    await executor.invoke_hook("on_workflow_start", ctx)
    types = [call.args[0].event_type for call in audit.emit.call_args_list]
    assert AuditEventType.PLUGIN_HOOK_INVOKED in types
    assert AuditEventType.PLUGIN_HOOK_COMPLETED in types


async def test_plugin_executor_timeout_emits_timeout_event() -> None:
    import asyncio

    async def slow_hook(ctx: PluginContext) -> None:
        await asyncio.sleep(999)

    plugin = MagicMock(spec=Plugin)
    plugin.name = "slow"
    plugin.on_workflow_start = slow_hook
    audit = AsyncMock()
    audit.emit = AsyncMock()
    executor = PluginExecutor([plugin], audit_service=audit, timeout_seconds=0.01)
    ctx = _make_ctx()
    await executor.invoke_hook("on_workflow_start", ctx)
    types = [call.args[0].event_type for call in audit.emit.call_args_list]
    assert AuditEventType.PLUGIN_HOOK_TIMEOUT in types


async def test_plugin_executor_exception_emits_failed_event() -> None:
    async def failing_hook(ctx: PluginContext) -> None:
        raise RuntimeError("boom")

    plugin = MagicMock(spec=Plugin)
    plugin.name = "broken"
    plugin.on_workflow_start = failing_hook
    audit = AsyncMock()
    audit.emit = AsyncMock()
    executor = PluginExecutor([plugin], audit_service=audit)
    ctx = _make_ctx()
    await executor.invoke_hook("on_workflow_start", ctx)
    types = [call.args[0].event_type for call in audit.emit.call_args_list]
    assert AuditEventType.PLUGIN_HOOK_FAILED in types


async def test_plugin_executor_no_audit_service_does_not_raise() -> None:
    plugin = _CleanPlugin()
    executor = PluginExecutor([plugin], audit_service=None)
    ctx = _make_ctx()
    await executor.invoke_hook("on_workflow_start", ctx)


async def test_plugin_executor_missing_hook_skips_gracefully() -> None:
    plugin = MagicMock(spec=Plugin)
    plugin.name = "no_hook"
    plugin.on_workflow_start = None
    executor = PluginExecutor([plugin], audit_service=None)
    ctx = _make_ctx()
    await executor.invoke_hook("on_workflow_start", ctx)


async def test_plugin_executor_invoke_on_node_execute() -> None:
    plugin = _CleanPlugin()
    executor = PluginExecutor([plugin], audit_service=None)
    await executor.invoke_on_node_execute(
        run_id="r1",
        workflow_id="wf-1",
        actor="a",
        namespace="ns",
        state={},
        node_id="node-1",
        output_state={"result": 42},
    )


# ---------------------------------------------------------------------------
# plugins/registry.py
# ---------------------------------------------------------------------------


def test_plugin_registry_load_missing_config_is_noop(tmp_path: Path) -> None:
    reg = PluginRegistry()
    reg.load_from_config(tmp_path / "nonexistent.yaml")
    assert reg.plugins == []


def test_plugin_registry_load_non_list_plugins_raises(tmp_path: Path) -> None:
    cfg = tmp_path / "plugins.yaml"
    cfg.write_text("plugins: not_a_list\n")
    reg = PluginRegistry()
    with pytest.raises(PluginConfigError, match="must be a list"):
        reg.load_from_config(cfg)


def test_plugin_registry_load_non_string_entry_raises(tmp_path: Path) -> None:
    cfg = tmp_path / "plugins.yaml"
    cfg.write_text("plugins:\n  - 123\n")
    reg = PluginRegistry()
    with pytest.raises(PluginConfigError, match="must be string"):
        reg.load_from_config(cfg)


def test_plugin_registry_rejects_file_path_entry(tmp_path: Path) -> None:
    cfg = tmp_path / "plugins.yaml"
    cfg.write_text("plugins:\n  - '/some/path/plugin.py'\n")
    reg = PluginRegistry()
    with pytest.raises(PluginConfigError, match="prohibited"):
        reg.load_from_config(cfg)


def test_plugin_registry_load_entry_point_colon_notation(tmp_path: Path) -> None:
    cfg = tmp_path / "plugins.yaml"
    cfg.write_text(
        "plugins:\n  - 'syndicateclaw.plugins.builtin.audit_trail:AuditTrailPlugin'\n"
    )
    reg = PluginRegistry()
    reg.load_from_config(cfg)
    assert len(reg.plugins) == 1
    assert reg.plugins[0].name == "audit_trail"


def test_load_entry_point_not_a_plugin_subclass_raises() -> None:
    from syndicateclaw.plugins.registry import _load_entry_point

    with pytest.raises(PluginConfigError, match="not a Plugin subclass"):
        _load_entry_point("syndicateclaw.plugins.base:PluginContext")


def test_load_entry_point_no_entry_point_match_raises() -> None:
    from syndicateclaw.plugins.registry import _load_entry_point

    with pytest.raises(PluginConfigError, match="No entry point"):
        _load_entry_point("nonexistent_plugin_name")


# ---------------------------------------------------------------------------
# channels/webhook.py
# ---------------------------------------------------------------------------


def test_webhook_channel_rejects_ssrf_url() -> None:
    from syndicateclaw.channels.webhook import WebhookChannel

    with pytest.raises(ValueError):
        WebhookChannel(base_url="http://169.254.169.254/metadata")


async def test_webhook_channel_send_success() -> None:
    from syndicateclaw.channels.webhook import WebhookChannel

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 200
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("syndicateclaw.channels.webhook._validate_url"):
        ch = WebhookChannel(
            base_url="https://hooks.example.com",
            auth_header="Bearer tok",
            httpx_client=mock_client,
        )
        result = await ch.send("hello", recipient="user-1", metadata={"k": "v"})
    assert result is True
    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["recipient"] == "user-1"
    assert kwargs["headers"]["Authorization"] == "Bearer tok"


async def test_webhook_channel_send_http_error_raises() -> None:
    from syndicateclaw.channels.webhook import WebhookChannel

    mock_resp = MagicMock(spec=httpx.Response)
    mock_resp.status_code = 500
    mock_resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "server error", request=MagicMock(), response=mock_resp
        )
    )
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.post = AsyncMock(return_value=mock_resp)

    with patch("syndicateclaw.channels.webhook._validate_url"), pytest.raises(
        httpx.HTTPStatusError
    ):
        ch = WebhookChannel(base_url="https://hooks.example.com", httpx_client=mock_client)
        await ch.send("msg", recipient="u")


async def test_webhook_channel_receive_raises_not_implemented() -> None:
    from syndicateclaw.channels.webhook import WebhookChannel

    with patch("syndicateclaw.channels.webhook._validate_url"), pytest.raises(
        NotImplementedError
    ):
        ch = WebhookChannel(
            base_url="https://hooks.example.com",
            httpx_client=AsyncMock(spec=httpx.AsyncClient),
        )
        async for _ in ch.receive():
            pass


# ---------------------------------------------------------------------------
# services/builder_token_service.py
# ---------------------------------------------------------------------------


def _make_token_record(
    *,
    token: str = "tok",
    token_type: str = "builder",
    workflow_id: str = "wf-1",
    actor: str = "user-1",
    expires_at: datetime | None = None,
) -> MagicMock:
    rec = MagicMock()
    rec.token = token
    rec.token_type = token_type
    rec.workflow_id = workflow_id
    rec.actor = actor
    rec.expires_at = expires_at or (datetime.now(UTC) + timedelta(hours=1))
    return rec


async def test_builder_token_issue_creates_token() -> None:
    repo = AsyncMock()
    repo.insert = AsyncMock()
    svc = BuilderTokenService(repo, ttl_seconds=3600)
    result = await svc.issue(workflow_id="wf-abc", actor="user-1")
    assert result.workflow_id == "wf-abc"
    assert len(result.token) > 0
    repo.insert.assert_awaited_once()


async def test_builder_token_validate_success() -> None:
    rec = _make_token_record()
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=rec)
    svc = BuilderTokenService(repo)
    actor = await svc.validate("tok", "wf-1")
    assert actor == "user-1"


async def test_builder_token_validate_not_found_raises() -> None:
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=None)
    svc = BuilderTokenService(repo)
    with pytest.raises(InvalidTokenError, match="not found"):
        await svc.validate("missing", "wf-1")


async def test_builder_token_validate_wrong_type_raises() -> None:
    rec = _make_token_record(token_type="streaming")
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=rec)
    svc = BuilderTokenService(repo)
    with pytest.raises(InvalidTokenError, match="Wrong token type"):
        await svc.validate("tok", "wf-1")


async def test_builder_token_validate_expired_raises() -> None:
    rec = _make_token_record(expires_at=datetime.now(UTC) - timedelta(hours=1))
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=rec)
    svc = BuilderTokenService(repo)
    with pytest.raises(InvalidTokenError, match="expired"):
        await svc.validate("tok", "wf-1")


async def test_builder_token_validate_wrong_workflow_raises() -> None:
    rec = _make_token_record(workflow_id="wf-other")
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=rec)
    svc = BuilderTokenService(repo)
    with pytest.raises(InvalidTokenError, match="not valid for this workflow"):
        await svc.validate("tok", "wf-1")


# ---------------------------------------------------------------------------
# tasks/org_cleanup.py
# ---------------------------------------------------------------------------


async def test_org_cleanup_skips_if_org_not_found() -> None:
    from syndicateclaw.tasks.org_cleanup import _cleanup_with_session

    session = AsyncMock()
    session.get = AsyncMock(return_value=None)
    await _cleanup_with_session(session, "org-missing")
    session.execute.assert_not_awaited()


async def test_org_cleanup_skips_if_not_deleting() -> None:
    from syndicateclaw.tasks.org_cleanup import _cleanup_with_session

    org = MagicMock()
    org.status = "ACTIVE"
    session = AsyncMock()
    session.get = AsyncMock(return_value=org)
    await _cleanup_with_session(session, "org-1")
    session.execute.assert_not_awaited()


async def test_org_cleanup_waits_if_active_runs() -> None:
    from syndicateclaw.tasks.org_cleanup import _cleanup_with_session

    org = MagicMock()
    org.status = "DELETING"
    org.namespace = "ns-1"

    count_result = MagicMock()
    count_result.scalar.return_value = 3

    session = AsyncMock()
    session.get = AsyncMock(return_value=org)
    session.execute = AsyncMock(return_value=count_result)
    await _cleanup_with_session(session, "org-1")
    assert session.execute.await_count == 1


async def test_org_cleanup_deletes_all_and_marks_deleted() -> None:
    from syndicateclaw.tasks.org_cleanup import _cleanup_with_session

    org = MagicMock()
    org.status = "DELETING"
    org.namespace = "ns-1"

    count_result = MagicMock()
    count_result.scalar.return_value = 0

    session = AsyncMock()
    session.get = AsyncMock(return_value=org)
    session.execute = AsyncMock(return_value=count_result)
    session.flush = AsyncMock()
    await _cleanup_with_session(session, "org-1")
    assert session.execute.await_count == 9  # count + 8 deletes
    assert org.status == "DELETED"
    session.flush.assert_awaited_once()
