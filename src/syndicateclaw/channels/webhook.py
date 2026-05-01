from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from syndicateclaw.channels import ChannelMessage
from syndicateclaw.security.ssrf import PinnedIPAsyncTransport, SSRFError, validate_url

logger = structlog.get_logger(__name__)


def _validate_url(url: str) -> str:
    """SSRF-hardened: delegate to ``security.ssrf.validate_url`` (DNS + blocklist)."""
    try:
        return validate_url(url)
    except SSRFError as exc:
        raise ValueError(str(exc)) from exc


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
        self._client = httpx_client

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
        pinned_ip = _validate_url(url)

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
            if self._client is not None:
                response = await self._client.post(url, json=payload, headers=headers)
            else:
                parsed = urlparse(url)
                if not parsed.hostname:
                    raise ValueError(f"Invalid URL: {url}")
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                transport = PinnedIPAsyncTransport(
                    pinned_ip=pinned_ip,
                    hostname=parsed.hostname,
                    scheme=parsed.scheme,
                    port=port,
                    timeout=30.0,
                )
                async with httpx.AsyncClient(timeout=30.0, transport=transport) as client:
                    response = await client.post(url, json=payload, headers=headers)
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
