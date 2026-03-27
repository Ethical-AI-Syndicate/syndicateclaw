"""Tests for syndicateclaw-sdk (v1.5.0) — no live server required."""

from __future__ import annotations

import os

import httpx
import pytest
from syndicateclaw_sdk import (
    BuildValidationError,
    IncompatibleServerError,
    LocalRuntime,
    WorkflowBuilder,
)
from syndicateclaw_sdk.client import SyndicateClaw


@pytest.mark.asyncio
async def test_sdk_version_check_compatible() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"version": "0.1.0", "title": "t"},
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as raw:
        client = SyndicateClaw(
            "http://test",
            min_server_version="0.0.1",
            http_client=raw,
        )
        await client.ensure_compatible()


@pytest.mark.asyncio
async def test_sdk_version_check_incompatible() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"version": "0.0.1", "title": "t"},
        )
    )
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as raw:
        client = SyndicateClaw(
            "http://test",
            min_server_version="1.5.0",
            http_client=raw,
        )
        with pytest.raises(IncompatibleServerError):
            await client.ensure_compatible()


def test_sdk_builder_missing_branch_raises() -> None:
    b = WorkflowBuilder()
    b.add_node({"id": "a", "type": "START"})
    b.add_node({"id": "b", "type": "DECISION", "config": {}})
    b.add_node({"id": "c", "type": "END"})
    with pytest.raises(BuildValidationError):
        b.build()


def test_sdk_local_runtime_production_guard() -> None:
    old = os.environ.get("SYNDICATECLAW_ENVIRONMENT")
    try:
        os.environ["SYNDICATECLAW_ENVIRONMENT"] = "production"
        with pytest.raises(RuntimeError):
            LocalRuntime()
    finally:
        if old is None:
            os.environ.pop("SYNDICATECLAW_ENVIRONMENT", None)
        else:
            os.environ["SYNDICATECLAW_ENVIRONMENT"] = old


def test_sdk_local_runtime_warns_on_construct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYNDICATECLAW_ENVIRONMENT", "development")
    with pytest.warns(UserWarning):
        LocalRuntime()
