"""Per-namespace schema enforcement for memory records.

Provides lightweight structural validation without requiring a full
JSON Schema engine. Schemas declare required fields, allowed types,
and optional field-level constraints per namespace.

Usage:
    registry = NamespaceSchemaRegistry()
    registry.register("agent:facts", NamespaceSchema(
        required_fields={"claim", "source_url"},
        field_types={"claim": "str", "source_url": "str", "confidence": "float"},
    ))
    registry.validate("agent:facts", {"claim": "Earth is round", "source_url": "..."})
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "str": str,
    "int": int,
    "float": (int, float),
    "bool": bool,
    "list": list,
    "dict": dict,
    "number": (int, float),
}


@dataclass(frozen=True)
class NamespaceSchema:
    """Structural schema for a memory namespace."""

    required_fields: set[str] = field(default_factory=set)
    field_types: dict[str, str] = field(default_factory=dict)
    max_field_count: int | None = None
    allow_extra_fields: bool = True


class SchemaValidationError(ValueError):
    """Raised when a memory value fails namespace schema validation."""


class NamespaceSchemaRegistry:
    """Registry mapping namespace patterns to structural schemas.

    Namespace matching supports exact match and prefix-glob (e.g.
    ``"agent:*"`` matches ``"agent:facts"``, ``"agent:context"``).
    """

    def __init__(self) -> None:
        self._schemas: dict[str, NamespaceSchema] = {}

    def register(self, namespace_pattern: str, schema: NamespaceSchema) -> None:
        self._schemas[namespace_pattern] = schema
        logger.info(
            "memory.schema.registered",
            namespace_pattern=namespace_pattern,
            required_fields=sorted(schema.required_fields),
        )

    def unregister(self, namespace_pattern: str) -> bool:
        return self._schemas.pop(namespace_pattern, None) is not None

    def get_schema(self, namespace: str) -> NamespaceSchema | None:
        if namespace in self._schemas:
            return self._schemas[namespace]
        for pattern, schema in self._schemas.items():
            if pattern.endswith("*") and namespace.startswith(pattern[:-1]):
                return schema
        return None

    def validate(self, namespace: str, value: Any) -> None:
        """Validate a value against its namespace schema. No-op if no schema registered."""
        schema = self.get_schema(namespace)
        if schema is None:
            return

        if not isinstance(value, dict):
            raise SchemaValidationError(
                f"Namespace '{namespace}' requires a dict value, got {type(value).__name__}"
            )

        if schema.required_fields:
            missing = schema.required_fields - set(value.keys())
            if missing:
                raise SchemaValidationError(
                    f"Namespace '{namespace}' missing required fields: {sorted(missing)}"
                )

        if schema.max_field_count is not None and len(value) > schema.max_field_count:
            raise SchemaValidationError(
                f"Namespace '{namespace}' value has {len(value)} fields, "
                f"max allowed is {schema.max_field_count}"
            )

        if not schema.allow_extra_fields:
            allowed = schema.required_fields | set(schema.field_types.keys())
            extra = set(value.keys()) - allowed
            if extra:
                raise SchemaValidationError(
                    f"Namespace '{namespace}' disallows extra fields: {sorted(extra)}"
                )

        for field_name, expected_type_name in schema.field_types.items():
            if field_name not in value:
                continue
            expected_types = _TYPE_MAP.get(expected_type_name)
            if expected_types is None:
                continue
            if not isinstance(value[field_name], expected_types):
                actual = type(value[field_name]).__name__
                raise SchemaValidationError(
                    f"Namespace '{namespace}' field '{field_name}' expected "
                    f"{expected_type_name}, got {actual}"
                )

    def list_schemas(self) -> dict[str, NamespaceSchema]:
        return dict(self._schemas)
