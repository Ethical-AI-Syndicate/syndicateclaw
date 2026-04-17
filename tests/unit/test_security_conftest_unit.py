from __future__ import annotations

from tests.security.conftest import _is_infrastructure_error


def test_infrastructure_error_matches_password_auth_failure() -> None:
    exc = RuntimeError('password authentication failed for user "syndicateclaw"')
    assert _is_infrastructure_error(exc) is True


def test_infrastructure_error_matches_connection_refused() -> None:
    exc = RuntimeError("Connect call failed: Connection refused")
    assert _is_infrastructure_error(exc) is True


def test_infrastructure_error_ignores_non_infra_errors() -> None:
    exc = RuntimeError("validation error: malformed payload")
    assert _is_infrastructure_error(exc) is False
