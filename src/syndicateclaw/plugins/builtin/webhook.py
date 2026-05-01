"""Webhook notification plugin with SSRF checks before each outbound request."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import httpx
import structlog

from syndicateclaw.plugins.base import Plugin, PluginContext
from syndicateclaw.security.ssrf import PinnedIPAsyncTransport, SSRFError, validate_url

logger = structlog.get_logger(__name__)


class WebhookPlugin(Plugin):
    """POST JSON to a configured URL; validates URL on every send."""

    name = "webhook"
    version = "1.0.0"

    def __init__(self, url: str) -> None:
        self._url = url

    async def on_workflow_end(self, ctx: PluginContext, status: str) -> None:
        env = os.environ.get("SYNDICATECLAW_ENVIRONMENT", "production").lower()
        parsed_scheme = self._url.split(":", 1)[0].lower() if ":" in self._url else ""
        if env not in {"development", "dev", "test", "testing"} and parsed_scheme != "https":
            raise SSRFError(self._url, "HTTPS required outside development environments")
        parsed = urlparse(self._url)
        if not parsed.hostname:
            raise SSRFError(self._url, "Missing hostname")
        try:
            pinned_ip = validate_url(self._url)
        except SSRFError:
            raise
        payload = {"run_id": ctx.run_id, "workflow_id": ctx.workflow_id, "status": status}
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        transport = PinnedIPAsyncTransport(
            pinned_ip=pinned_ip,
            hostname=parsed.hostname,
            scheme=parsed.scheme,
            port=port,
            timeout=10.0,
        )
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=10.0,
            transport=transport,
        ) as client:
            response = await client.post(self._url, json=payload)
            response.raise_for_status()
