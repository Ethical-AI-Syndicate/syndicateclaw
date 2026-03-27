"""AST-based static checks for plugin classes."""

from __future__ import annotations

import ast
import inspect
from typing import Any


class PluginSecurityViolationError(Exception):
    """Raised when a plugin class fails static security analysis."""


BANNED_CALLS = frozenset(
    {
        "create_task",
        "ensure_future",
        "Thread",
        "Process",
        "system",
        "popen",
        "exec",
        "eval",
        "compile",
    }
)
BANNED_IMPORT_ROOTS = frozenset(
    {
        "asyncio",
        "threading",
        "multiprocessing",
        "subprocess",
        "importlib",
    }
)


def check_plugin_security(plugin_class: type[Any]) -> None:
    """Inspect plugin source for banned calls and imports."""
    try:
        source = inspect.getsource(plugin_class)
    except OSError as exc:
        raise PluginSecurityViolationError(
            f"Cannot read source for {plugin_class!r}: {exc}"
        ) from exc

    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name: str | None = None
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            elif isinstance(node.func, ast.Name):
                name = node.func.id
            if name in BANNED_CALLS:
                raise PluginSecurityViolationError(f"Banned call: {name}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in BANNED_IMPORT_ROOTS:
                    raise PluginSecurityViolationError(f"Banned import: {alias.name}")
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            root = mod.split(".", 1)[0] if mod else ""
            if root in BANNED_IMPORT_ROOTS:
                raise PluginSecurityViolationError(f"Banned import: {mod}")
            for alias in node.names:
                if alias.name.split(".", 1)[0] in BANNED_IMPORT_ROOTS:
                    raise PluginSecurityViolationError(f"Banned import: {alias.name}")
