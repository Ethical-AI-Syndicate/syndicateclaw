"""JSON Schema validation for skill payloads (jsonschema draft 2020-12).

Manifest ``input_schema`` / ``output_schema`` are arbitrary JSON Schema objects stored on
:class:`~syndicateclaw.runtime.contracts.skill_manifest.SkillManifest`. Execution validates
handler I/O with the **same** embedded dicts — there is no parallel schema source that can
drift from the manifest for runtime enforcement.

Structural validation of the manifest itself is Pydantic; I/O enforcement is ``jsonschema``.
``additionalProperties`` and nullability follow the embedded schemas only.
"""

from __future__ import annotations

from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

from syndicateclaw.runtime.errors import ExecutionValidationError


def validate_payload_against_schema(
    payload: dict[str, Any],
    schema: dict[str, Any],
    *,
    label: str,
) -> None:
    """Validate payload; empty schema {} accepts any JSON value per JSON Schema."""
    try:
        Draft202012Validator(schema).validate(payload)
    except jsonschema.ValidationError as e:
        msg = f"{label} failed JSON Schema validation: {e.message}"
        raise ExecutionValidationError(msg) from e
