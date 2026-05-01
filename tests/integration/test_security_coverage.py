"""Security module integration-style tests (SSRF, JWT verification)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from syndicateclaw.security.auth import decode_access_token
from syndicateclaw.security.ssrf import SSRFError, validate_url

pytestmark = pytest.mark.integration


def test_ssrf_validate_url_blocks_private_ranges() -> None:
    for url in (
        "http://127.0.0.1/api",
        "http://192.168.1.1/x",
        "http://10.0.0.1/x",
        "http://169.254.0.1/x",
        "http://[::1]/x",
    ):
        with pytest.raises(SSRFError):
            validate_url(url)


def test_ssrf_validate_url_allows_public_address() -> None:
    assert validate_url("https://example.com/path")


def test_secondary_jwt_key_fallback() -> None:
    primary = "primary-secret-key-not-for-prod!!"
    secondary = "secondary-secret-key-not-for-prod!!"
    claims = {
        "sub": "user-1",
        "exp": datetime.now(UTC) + timedelta(hours=1),
    }
    token = jwt.encode(claims, secondary, algorithm="HS256")
    out = decode_access_token(
        token,
        secret_key=primary,
        secondary_secret_key=secondary,
    )
    assert out["sub"] == "user-1"


@pytest.mark.skip(
    reason=(
        "Requires Redis + app state for revocation list; run manually. "
        "Unskip: v1.2 when revocation list is wired into the integration test fixture."
    )
)
async def test_revoked_token_rejected() -> None:
    pass
