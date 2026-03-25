from __future__ import annotations

from collections.abc import AsyncIterator
from ipaddress import ip_address
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from syndicateclaw.channels import ChannelMessage

logger = structlog.get_logger(__name__)

_BLOCKED_NETWORKS = ("127.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
                     "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
                     "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
                     "172.30.", "172.31.", "192.168.", "0.", "169.254.")


def _validate_url(url: str) -> None:
    """Raise ValueError if the URL targets a private/loopback address (SSRF protection)."""
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    if not parsed.scheme or parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme!r}")

    if hostname in ("localhost", ""):
        raise ValueError(f"Blocked hostname: {hostname!r}")

    try:
        addr = ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_reserved or addr.is_link_local:
            raise ValueError(f"Blocked private/reserved IP: {addr}")
    except ValueError as exc:
        if "Blocked" in str(exc):
            raise
        # hostname is not a raw IP — check common prefixes
        for prefix in _BLOCKED_NETWORKS:
            if hostname.startswith(prefix):
                raise ValueError(f"Blocked hostname prefix: {hostname!r}") from None


class WebhookChannel:
    """Channel connector that delivers messages via outbound HTTP webhooks."""

    channel_name: str = "webhook"

    def __init__(
        self,
        base_url: str,
        auth_header: str | None = None,
        httpx_client: httpx.AsyncClient | None = None,
    ) -> None:
        _validate_url(base_url)
        self._base_url = base_url.rstrip("/")
        self._auth_header = auth_header
        self._client = httpx_client or httpx.AsyncClient(timeout=30)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(httpx.TransportError),
        reraise=True,
    )
    async def send(
        self, message: str, recipient: str, metadata: dict[str, Any] | None = None
    ) -> bool:
        metadata = metadata or {}
        url = f"{self._base_url}/{recipient}"
        _validate_url(url)

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._auth_header:
            headers["Authorization"] = self._auth_header

        payload = {
            "message": message,
            "recipient": recipient,
            "metadata": metadata,
        }

        log = logger.bind(url=url, recipient=recipient)
        log.info("webhook_send_attempt")

        try:
            response = await self._client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            log.info("webhook_send_success", status=response.status_code)
            return True
        except httpx.HTTPStatusError as exc:
            log.error("webhook_send_http_error", status=exc.response.status_code)
            raise
        except httpx.TransportError as exc:
            log.error("webhook_send_transport_error", error=str(exc))
            raise

    async def receive(self) -> AsyncIterator[ChannelMessage]:
        raise NotImplementedError(
            "WebhookChannel is send-only; inbound webhooks are handled by the API layer."
        )
        yield  # pragma: no cover – makes the function an async generator
