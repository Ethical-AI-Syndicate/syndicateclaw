"""Webhook channel SSRF alignment with ``security.ssrf.validate_url``."""

from __future__ import annotations

import pytest

from syndicateclaw.channels.webhook import WebhookChannel


def test_webhook_channel_rejects_private_ip_target() -> None:
    with pytest.raises(ValueError):
        WebhookChannel(base_url="http://127.0.0.1/hook")
