"""Unit tests for tools/builtin.py — handler functions and registry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syndicateclaw.tools.builtin import (
    BUILTIN_TOOLS,
    http_request_handler,
    memory_read_handler,
    memory_write_handler,
)

# ---------------------------------------------------------------------------
# http_request_handler
# ---------------------------------------------------------------------------


async def test_http_request_handler_invalid_url_no_hostname() -> None:
    with pytest.raises(ValueError, match="Invalid URL"):
        await http_request_handler({"url": "not-a-url"})


async def test_http_request_handler_ssrf_blocked() -> None:
    from syndicateclaw.security.ssrf import SSRFError

    with (
        patch(
            "syndicateclaw.tools.builtin.validate_url",
            side_effect=SSRFError("http://192.168.1.1/evil", "private IP"),
        ),
        pytest.raises(PermissionError, match="SSRF blocked"),
    ):
        await http_request_handler({"url": "http://192.168.1.1/evil"})


async def test_http_request_handler_get_success() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "text/plain"}
    mock_response.text = "hello world"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.request = AsyncMock(return_value=mock_response)

    with (
        patch("syndicateclaw.tools.builtin.validate_url"),
        patch("syndicateclaw.tools.builtin.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await http_request_handler({"url": "http://example.com"})

    assert result["status_code"] == 200
    assert result["body"] == "hello world"
    assert "content-type" in result["headers"]


async def test_http_request_handler_post_with_body() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.headers = {}
    mock_response.text = "created"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.request = AsyncMock(return_value=mock_response)

    with (
        patch("syndicateclaw.tools.builtin.validate_url"),
        patch("syndicateclaw.tools.builtin.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await http_request_handler(
            {
                "url": "http://example.com/api",
                "method": "POST",
                "headers": {"Content-Type": "application/json"},
                "body": '{"key": "val"}',
            }
        )

    assert result["status_code"] == 201
    assert result["body"] == "created"
    # Verify body was encoded and passed
    call_kwargs = mock_client.request.call_args
    assert call_kwargs.kwargs["content"] == b'{"key": "val"}'


async def test_http_request_handler_no_body_sends_none() -> None:
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {}
    mock_response.text = "ok"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.request = AsyncMock(return_value=mock_response)

    with (
        patch("syndicateclaw.tools.builtin.validate_url"),
        patch("syndicateclaw.tools.builtin.httpx.AsyncClient", return_value=mock_client),
    ):
        await http_request_handler({"url": "http://example.com", "method": "DELETE"})

    call_kwargs = mock_client.request.call_args
    assert call_kwargs.kwargs["content"] is None


# ---------------------------------------------------------------------------
# memory_write_handler
# ---------------------------------------------------------------------------


async def test_memory_write_handler_stores_and_returns_key() -> None:
    result = await memory_write_handler(
        {
            "key": "mykey",
            "value": "myval",
            "namespace": "test-ns",
        }
    )
    assert result["key"] == "mykey"
    assert result["written"] is True


async def test_memory_write_handler_default_namespace() -> None:
    result = await memory_write_handler({"key": "k2", "value": "v2"})
    assert result["written"] is True


# ---------------------------------------------------------------------------
# memory_read_handler
# ---------------------------------------------------------------------------


async def test_memory_read_handler_found_after_write() -> None:
    ns = "rns-found"
    await memory_write_handler({"key": "rkey", "value": "rval", "namespace": ns})
    result = await memory_read_handler({"key": "rkey", "namespace": ns})
    assert result["found"] is True
    assert result["value"] == "rval"
    assert result["key"] == "rkey"


async def test_memory_read_handler_not_found() -> None:
    result = await memory_read_handler({"key": "missing", "namespace": "noexist"})
    assert result["found"] is False
    assert result["value"] == ""


async def test_memory_read_handler_default_namespace() -> None:
    await memory_write_handler({"key": "defkey", "value": "defval"})
    result = await memory_read_handler({"key": "defkey"})
    assert result["found"] is True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_builtin_tools_registry_has_three_entries() -> None:
    assert len(BUILTIN_TOOLS) == 3
    names = [tool.name for tool, _ in BUILTIN_TOOLS]
    assert "http_request" in names
    assert "memory_write" in names
    assert "memory_read" in names


def test_builtin_tools_all_have_handlers() -> None:
    for tool, handler in BUILTIN_TOOLS:
        assert callable(handler)
        assert tool.name
        assert tool.version
