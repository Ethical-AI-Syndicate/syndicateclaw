from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from syndicateclaw.models import Tool, ToolRiskLevel

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------

_BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private_ip(host: str) -> bool:
    """Return True if *host* resolves to any private/internal IP."""
    try:
        addr_infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return True

    for _, _, _, _, sockaddr in addr_infos:
        ip = ipaddress.ip_address(sockaddr[0])
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                return True
    return False


# ---------------------------------------------------------------------------
# http_request tool
# ---------------------------------------------------------------------------

http_request_tool = Tool(
    name="http_request",
    description="Makes an HTTP request to a public URL with SSRF protection.",
    version="1.0.0",
    risk_level=ToolRiskLevel.MEDIUM,
    input_schema={
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string"},
            "method": {"type": "string"},
            "headers": {"type": "object"},
            "body": {"type": "string"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "status_code": {"type": "integer"},
            "headers": {"type": "object"},
            "body": {"type": "string"},
        },
    },
    idempotent=False,
    timeout_seconds=30,
    owner="syndicateclaw",
)


async def http_request_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    url = input_data["url"]
    method = input_data.get("method", "GET").upper()
    headers = input_data.get("headers", {})
    body = input_data.get("body")

    parsed = urlparse(url)
    if not parsed.hostname:
        raise ValueError(f"Invalid URL: {url}")

    if _is_private_ip(parsed.hostname):
        raise PermissionError(
            f"SSRF blocked: {parsed.hostname} resolves to a private IP"
        )

    async with httpx.AsyncClient(timeout=25.0) as client:
        response = await client.request(
            method,
            url,
            headers=headers,
            content=body.encode() if body else None,
        )

    return {
        "status_code": response.status_code,
        "headers": dict(response.headers),
        "body": response.text[:100_000],
    }


# ---------------------------------------------------------------------------
# memory_write tool
# ---------------------------------------------------------------------------

memory_write_tool = Tool(
    name="memory_write",
    description="Writes a key-value pair to the memory service.",
    version="1.0.0",
    risk_level=ToolRiskLevel.LOW,
    input_schema={
        "type": "object",
        "required": ["key", "value"],
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
            "namespace": {"type": "string"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "written": {"type": "boolean"},
        },
    },
    idempotent=True,
    timeout_seconds=10,
    owner="syndicateclaw",
)

_memory_store: dict[str, dict[str, str]] = {}


async def memory_write_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    namespace = input_data.get("namespace", "default")
    key = input_data["key"]
    value = input_data["value"]

    _memory_store.setdefault(namespace, {})[key] = value

    logger.info("memory.write", namespace=namespace, key=key)
    return {"key": key, "written": True}


# ---------------------------------------------------------------------------
# memory_read tool
# ---------------------------------------------------------------------------

memory_read_tool = Tool(
    name="memory_read",
    description="Reads a value from the memory service by key.",
    version="1.0.0",
    risk_level=ToolRiskLevel.LOW,
    input_schema={
        "type": "object",
        "required": ["key"],
        "properties": {
            "key": {"type": "string"},
            "namespace": {"type": "string"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
            "found": {"type": "boolean"},
        },
    },
    idempotent=True,
    timeout_seconds=10,
    owner="syndicateclaw",
)


async def memory_read_handler(input_data: dict[str, Any]) -> dict[str, Any]:
    namespace = input_data.get("namespace", "default")
    key = input_data["key"]

    ns = _memory_store.get(namespace, {})
    value = ns.get(key)

    logger.info("memory.read", namespace=namespace, key=key, found=value is not None)
    return {"key": key, "value": value or "", "found": value is not None}


# ---------------------------------------------------------------------------
# Registry helper
# ---------------------------------------------------------------------------

BUILTIN_TOOLS: list[tuple[Tool, Any]] = [
    (http_request_tool, http_request_handler),
    (memory_write_tool, memory_write_handler),
    (memory_read_tool, memory_read_handler),
]
