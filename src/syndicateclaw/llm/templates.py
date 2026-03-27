from __future__ import annotations

from typing import Any

from jinja2 import StrictUndefined
from jinja2.sandbox import SandboxedEnvironment


def _environment() -> SandboxedEnvironment:
    return SandboxedEnvironment(undefined=StrictUndefined, autoescape=False)


def render_message_template(template: str, context: dict[str, Any]) -> str:
    """Render a message template in a strict sandboxed environment."""
    env = _environment()
    compiled = env.from_string(template)
    return str(compiled.render(**context))
