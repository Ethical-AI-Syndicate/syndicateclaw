"""SyndicateClaw validation helpers."""

from datetime import datetime
from typing import Any

from syndicateclaw.errors import ValidationError


def ValidateULID(value: str) -> str:
    """
    Validate a ULID string.

    Args:
        value: The ULID string to validate.

    Returns:
        The validated ULID string.

    Raises:
        ValidationError: If the ULID is invalid.
    """
    if not value:
        raise ValidationError("ULID cannot be empty")

    if len(value) != 26:
        raise ValidationError(f"ULID must be 26 characters, got {len(value)}")

    # ULID uses Crockford's base32 encoding
    _ULID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    for char in value.upper():
        if char not in _ULID_ALPHABET:
            raise ValidationError(f"Invalid ULID character: {char}")

    return value.upper()


def ValidateTimestamp(value: datetime | str | None) -> datetime | None:
    """
    Validate and normalize a timestamp.

    Args:
        value: A datetime object, ISO format string, or None.

    Returns:
        A datetime object or None.

    Raises:
        ValidationError: If the timestamp format is invalid.
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        try:
            # Try ISO format
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValidationError(f"Invalid timestamp format: {value}")

    raise ValidationError(f"Timestamp must be datetime or string, got {type(value)}")


def ValidateNamespace(value: str, max_length: int = 128) -> str:
    """
    Validate a memory namespace string.

    Args:
        value: The namespace string to validate.
        max_length: Maximum allowed length.

    Returns:
        The validated namespace string.

    Raises:
        ValidationError: If the namespace is invalid.
    """
    if not value:
        raise ValidationError("Namespace cannot be empty")

    if len(value) > max_length:
        raise ValidationError(f"Namespace too long: {len(value)} > {max_length}")

    # Namespace should be a valid identifier (alphanumeric with colons and underscores)
    import re

    if not re.match(r"^[a-zA-Z0-9_:]+$", value):
        raise ValidationError(f"Namespace contains invalid characters: {value}")

    return value


def ValidateKey(value: str, max_length: int = 256) -> str:
    """
    Validate a memory key string.

    Args:
        value: The key string to validate.
        max_length: Maximum allowed length.

    Returns:
        The validated key string.

    Raises:
        ValidationError: If the key is invalid.
    """
    if not value:
        raise ValidationError("Key cannot be empty")

    if len(value) > max_length:
        raise ValidationError(f"Key too long: {len(value)} > {max_length}")

    import re

    if not re.match(r"^[a-zA-Z0-9_:.-]+$", value):
        raise ValidationError(f"Key contains invalid characters: {value}")

    return value


def ValidateActor(value: str) -> str:
    """
    Validate an actor/principal identifier.

    Args:
        value: The actor identifier to validate.

    Returns:
        The validated actor string.

    Raises:
        ValidationError: If the actor is invalid.
    """
    if not value:
        raise ValidationError("Actor cannot be empty")

    if len(value) > 256:
        raise ValidationError(f"Actor too long: {len(value)} > 256")

    import re

    if not re.match(r"^[a-zA-Z0-9_:.@/-]+$", value):
        raise ValidationError(f"Actor contains invalid characters: {value}")

    return value


def ValidateResourceType(value: str) -> str:
    """
    Validate a resource type string.

    Args:
        value: The resource type to validate.

    Returns:
        The validated resource type string.

    Raises:
        ValidationError: If the resource type is invalid.
    """
    if not value:
        raise ValidationError("Resource type cannot be empty")

    if len(value) > 64:
        raise ValidationError(f"Resource type too long: {len(value)} > 64")

    import re

    if not re.match(r"^[a-z][a-z0-9_]*$", value):
        raise ValidationError(
            f"Resource type must be lowercase alphanumeric with underscores: {value}"
        )

    return value


def ValidateAction(value: str) -> str:
    """
    Validate an action string.

    Args:
        value: The action to validate.

    Returns:
        The validated action string.

    Raises:
        ValidationError: If the action is invalid.
    """
    if not value:
        raise ValidationError("Action cannot be empty")

    if len(value) > 64:
        raise ValidationError(f"Action too long: {len(value)} > 64")

    import re

    if not re.match(r"^[a-z][a-z0-9_]*$", value):
        raise ValidationError(f"Action must be lowercase alphanumeric with underscores: {value}")

    return value


def ValidateUrl(url: str) -> str:
    """
    Validate a URL string.

    Args:
        value: The URL to validate.

    Returns:
        The validated URL string.

    Raises:
        ValidationError: If the URL is invalid.
    """
    if not url:
        raise ValidationError("URL cannot be empty")

    import re

    url_pattern = re.compile(
        r"^https?://"  # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"  # domain
        r"localhost|"  # localhost
        r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"  # or IP
        r"(?::\d+)?"  # optional port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )

    if not url_pattern.match(url):
        raise ValidationError(f"Invalid URL format: {url}")

    return url
