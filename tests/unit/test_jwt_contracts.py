"""Contract tests: JWTs carry identity and org context only; permissions come from RBAC."""

from __future__ import annotations

from datetime import timedelta

import jwt
import pytest

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
