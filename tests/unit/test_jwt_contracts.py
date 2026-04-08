"""Contract tests: JWTs carry identity and org context only; permissions come from RBAC."""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import timedelta
from unittest.mock import MagicMock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from syndicateclaw.security.auth import JWTError, create_access_token, decode_access_token


def test_create_access_token_never_embeds_permissions_claim() -> None:
    """Issuer path must not add a permissions claim (resolved live from RBAC)."""
    secret = "unit-test-secret-key-not-for-production-use"
    token = create_access_token(
        "actor-1",
        timedelta(minutes=5),
        org_id="org-9",
        org_role="MEMBER",
        secret_key=secret,
    )
    claims = jwt.decode(token, secret, algorithms=["HS256"], options={"verify_exp": True})
    assert "permissions" not in claims
    assert claims["sub"] == "actor-1"
    assert claims["org_id"] == "org-9"
    assert claims["org_role"] == "MEMBER"


def test_decode_access_token_round_trip_matches_create() -> None:
    secret = "unit-test-secret-key-not-for-production-use"
    raw = create_access_token("u2", timedelta(minutes=1), secret_key=secret)
    claims = decode_access_token(raw, secret_key=secret)
    assert claims.get("sub") == "u2"
    assert "permissions" not in claims


def test_decode_rejects_token_signed_with_non_allowlisted_algorithm() -> None:
    """Algorithms are fixed at decode time; header cannot force 'none'."""
    secret = "unit-test-secret-key-not-for-production-use"
    # Unsigned / wrong alg — PyJWT rejects when only HS256 is allowed
    bogus = jwt.encode({"sub": "evil", "exp": 9999999999}, "", algorithm="none")
    with pytest.raises(JWTError):
        decode_access_token(bogus, secret_key=secret)


def test_decode_accepts_rs256_token_via_oidc_jwks() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "oidc-user",
            "iss": "https://accounts.google.com",
            "aud": "syndicateclaw-api",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "google-kid-1"},
    )
    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

    with patch("syndicateclaw.security.auth._get_jwks_client", return_value=mock_client):
        claims = decode_access_token(
            token,
            audience="syndicateclaw-api",
            oidc_jwks_url="https://www.googleapis.com/oauth2/v3/certs",
            issuer="https://accounts.google.com",
        )

    assert claims["sub"] == "oidc-user"


def test_decode_rejects_rs256_token_with_wrong_oidc_issuer() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "oidc-user",
            "iss": "https://accounts.google.com",
            "aud": "syndicateclaw-api",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "google-kid-1"},
    )
    mock_signing_key = MagicMock()
    mock_signing_key.key = public_key
    mock_client = MagicMock()
    mock_client.get_signing_key_from_jwt.return_value = mock_signing_key

    with patch("syndicateclaw.security.auth._get_jwks_client", return_value=mock_client):
        with pytest.raises(JWTError):
            decode_access_token(
                token,
                audience="syndicateclaw-api",
                oidc_jwks_url="https://www.googleapis.com/oauth2/v3/certs",
                issuer="https://issuer.example.com",
            )
