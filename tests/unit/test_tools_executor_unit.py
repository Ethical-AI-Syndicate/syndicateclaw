"""Unit tests for tools/executor.py — exception classes, schema validation, sandbox enforcement."""
from __future__ import annotations

import pytest

from syndicateclaw.models import ToolSandboxPolicy
from syndicateclaw.tools.executor import (
    SandboxViolationError,
    ToolDeniedError,
    ToolExecutionError,
    ToolNotFoundError,
    ToolTimeoutError,
    _validate_schema,
    enforce_sandbox,
)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------


def test_tool_not_found_error_message() -> None:
    err = ToolNotFoundError("my-tool")
    assert "my-tool" in str(err)
    assert err.name == "my-tool"


def test_tool_denied_error_with_reason() -> None:
    err = ToolDeniedError("my-tool", "policy deny")
    assert "my-tool" in str(err)
    assert "policy deny" in str(err)
    assert err.name == "my-tool"
    assert err.reason == "policy deny"


def test_tool_denied_error_without_reason() -> None:
    err = ToolDeniedError("my-tool")
    assert "my-tool" in str(err)
    assert err.reason == ""


def test_tool_timeout_error_message() -> None:
    err = ToolTimeoutError("slow-tool", 30)
    assert "slow-tool" in str(err)
    assert "30" in str(err)
    assert err.name == "slow-tool"
    assert err.timeout == 30


def test_tool_execution_error_message() -> None:
    cause = ValueError("db error")
    err = ToolExecutionError("my-tool", cause)
    assert "my-tool" in str(err)
    assert err.name == "my-tool"
    assert err.cause is cause


def test_sandbox_violation_error_message() -> None:
    err = SandboxViolationError("my-tool", "network denied")
    assert "my-tool" in str(err)
    assert "network denied" in str(err)
    assert err.name == "my-tool"
    assert err.violation == "network denied"


# ---------------------------------------------------------------------------
# _validate_schema
# ---------------------------------------------------------------------------


def test_validate_schema_empty_schema_passes() -> None:
    _validate_schema({"key": "val"}, {}, "test")  # no error


def test_validate_schema_required_field_present_passes() -> None:
    schema = {"required": ["url"], "properties": {}}
    _validate_schema({"url": "http://example.com"}, schema, "test")


def test_validate_schema_missing_required_raises() -> None:
    schema = {"required": ["url"]}
    with pytest.raises(ValueError, match="missing required field"):
        _validate_schema({}, schema, "test")


def test_validate_schema_correct_type_passes() -> None:
    schema = {"properties": {"count": {"type": "integer"}}}
    _validate_schema({"count": 5}, schema, "test")


def test_validate_schema_wrong_type_raises() -> None:
    schema = {"properties": {"count": {"type": "integer"}}}
    with pytest.raises(ValueError, match="expected type integer"):
        _validate_schema({"count": "five"}, schema, "test")


def test_validate_schema_missing_optional_field_passes() -> None:
    schema = {"properties": {"count": {"type": "integer"}}}
    _validate_schema({}, schema, "test")  # count is optional


def test_validate_schema_string_type_passes() -> None:
    schema = {"properties": {"name": {"type": "string"}}}
    _validate_schema({"name": "hello"}, schema, "test")


def test_validate_schema_boolean_type_passes() -> None:
    schema = {"properties": {"active": {"type": "boolean"}}}
    _validate_schema({"active": True}, schema, "test")


def test_validate_schema_number_type_accepts_float() -> None:
    schema = {"properties": {"score": {"type": "number"}}}
    _validate_schema({"score": 3.14}, schema, "test")


def test_validate_schema_array_type_passes() -> None:
    schema = {"properties": {"items": {"type": "array"}}}
    _validate_schema({"items": [1, 2, 3]}, schema, "test")


def test_validate_schema_object_type_passes() -> None:
    schema = {"properties": {"meta": {"type": "object"}}}
    _validate_schema({"meta": {"key": "val"}}, schema, "test")


def test_validate_schema_unknown_type_skips_check() -> None:
    schema = {"properties": {"x": {"type": "custom_type"}}}
    _validate_schema({"x": object()}, schema, "test")  # no error for unknown type


# ---------------------------------------------------------------------------
# enforce_sandbox
# ---------------------------------------------------------------------------


def _default_policy(**overrides) -> ToolSandboxPolicy:
    defaults = dict(
        network_isolation=False,
        allowed_protocols=["http", "https"],
        allowed_domains=[],
        max_request_bytes=1024 * 1024,
        subprocess_allowed=False,
        filesystem_read=False,
        filesystem_write=False,
    )
    defaults.update(overrides)
    return ToolSandboxPolicy(**defaults)


def test_enforce_sandbox_passes_with_empty_input() -> None:
    policy = _default_policy()
    enforce_sandbox("tool", {}, policy)  # no error


def test_enforce_sandbox_network_isolation_blocks_url() -> None:
    policy = _default_policy(network_isolation=True)
    with pytest.raises(SandboxViolationError, match="network access denied"):
        enforce_sandbox("tool", {"url": "http://example.com"}, policy)


def test_enforce_sandbox_network_isolation_passes_without_url() -> None:
    policy = _default_policy(network_isolation=True)
    enforce_sandbox("tool", {"data": "safe"}, policy)  # no url, no error


def test_enforce_sandbox_disallowed_protocol_raises() -> None:
    policy = _default_policy(allowed_protocols=["https"])
    with pytest.raises(SandboxViolationError, match="protocol 'http'"):
        enforce_sandbox("tool", {"url": "http://example.com"}, policy)


def test_enforce_sandbox_allowed_protocol_passes() -> None:
    policy = _default_policy(allowed_protocols=["https"])
    enforce_sandbox("tool", {"url": "https://example.com"}, policy)


def test_enforce_sandbox_domain_not_in_allowlist_raises() -> None:
    policy = _default_policy(allowed_domains=["allowed.com"])
    with pytest.raises(SandboxViolationError, match="domain"):
        enforce_sandbox("tool", {"url": "https://evil.com"}, policy)


def test_enforce_sandbox_domain_in_allowlist_passes() -> None:
    policy = _default_policy(allowed_domains=["allowed.com"])
    enforce_sandbox("tool", {"url": "https://allowed.com/path"}, policy)


def test_enforce_sandbox_empty_allowlist_allows_any_domain() -> None:
    policy = _default_policy(allowed_domains=[])
    enforce_sandbox("tool", {"url": "https://any.com"}, policy)


def test_enforce_sandbox_max_request_bytes_exceeded_raises() -> None:
    policy = _default_policy(max_request_bytes=10)
    large_body = "x" * 20
    with pytest.raises(SandboxViolationError, match="bytes exceeds limit"):
        enforce_sandbox("tool", {"body": large_body}, policy)


def test_enforce_sandbox_body_within_limit_passes() -> None:
    policy = _default_policy(max_request_bytes=1000)
    enforce_sandbox("tool", {"body": "small body"}, policy)


def test_enforce_sandbox_bytes_body_checked() -> None:
    policy = _default_policy(max_request_bytes=5)
    with pytest.raises(SandboxViolationError, match="bytes exceeds limit"):
        enforce_sandbox("tool", {"body": b"too many bytes here"}, policy)


def test_enforce_sandbox_subprocess_denied_raises() -> None:
    policy = _default_policy(subprocess_allowed=False)
    with pytest.raises(SandboxViolationError, match="subprocess execution denied"):
        enforce_sandbox("tool", {"subprocess": "ls -la"}, policy)


def test_enforce_sandbox_subprocess_allowed_passes() -> None:
    policy = _default_policy(subprocess_allowed=True)
    enforce_sandbox("tool", {"subprocess": "ls -la"}, policy)


def test_enforce_sandbox_filesystem_read_denied_raises() -> None:
    policy = _default_policy(filesystem_read=False)
    with pytest.raises(SandboxViolationError, match="filesystem read denied"):
        enforce_sandbox("tool", {"file_path": "/etc/passwd"}, policy)


def test_enforce_sandbox_filesystem_read_allowed_passes() -> None:
    policy = _default_policy(filesystem_read=True)
    enforce_sandbox("tool", {"file_path": "/etc/passwd"}, policy)
