"""Regression: user-controlled URLs must not reach internal/reserved addresses."""

from __future__ import annotations

import pytest

from syndicateclaw.security.ssrf import SSRFError, validate_url


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "https://10.0.0.1/path",
        "http://192.168.0.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
    ],
)
def test_validate_url_blocks_private_and_loopback(url: str) -> None:
    with pytest.raises(SSRFError):
        validate_url(url)


def test_validate_url_rejects_non_http_scheme() -> None:
    with pytest.raises(SSRFError, match="Unsupported scheme"):
        validate_url("file:///etc/passwd")


def test_validate_url_rejects_missing_hostname() -> None:
    with pytest.raises(SSRFError, match="Missing hostname"):
        validate_url("http:///nohost")
