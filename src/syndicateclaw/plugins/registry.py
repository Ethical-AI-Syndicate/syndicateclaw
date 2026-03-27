"""Load plugins from YAML config using entry points only (no file paths)."""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import structlog
import yaml

from syndicateclaw.plugins.base import Plugin
from syndicateclaw.plugins.security import check_plugin_security

logger = structlog.get_logger(__name__)


class PluginConfigError(Exception):
    """Invalid plugin configuration."""


class PluginRegistry:
    def __init__(self) -> None:
        self.plugins: list[Plugin] = []

    def register(self, plugin: Plugin) -> None:
        self.plugins.append(plugin)

    def load_from_config(self, config_path: Path) -> None:
        if not config_path.exists():
            logger.info("plugins.config_missing", path=str(config_path))
            return
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        entries = raw.get("plugins") or []
        if not isinstance(entries, list):
            raise PluginConfigError("'plugins' must be a list")

        for entry in entries:
            if not isinstance(entry, str):
                raise PluginConfigError(f"Plugin entry must be string, got {entry!r}")
            if "/" in entry or entry.endswith(".py") or os.path.sep in entry:
                raise PluginConfigError(
                    f"File-path plugin loading is prohibited: {entry!r}. "
                    "Install as a Python package and use entry point format: 'module:ClassName'"
                )
            cls = _load_entry_point(entry)
            check_plugin_security(cls)
            self.register(cls())


def _load_entry_point(qualified_name: str) -> type[Plugin]:
    if ":" in qualified_name:
        module_path, class_name = qualified_name.rsplit(":", 1)
        module = importlib.import_module(module_path)
        obj = getattr(module, class_name)
        if not isinstance(obj, type) or not issubclass(obj, Plugin):
            raise PluginConfigError(f"{qualified_name!r} is not a Plugin subclass")
        return obj

    from importlib.metadata import entry_points

    eps = entry_points(group="syndicateclaw.plugins")
    matches = [ep for ep in eps if ep.name == qualified_name]
    if not matches:
        raise PluginConfigError(f"No entry point for: {qualified_name!r}")
    loaded = matches[0].load()
    if not isinstance(loaded, type) or not issubclass(loaded, Plugin):
        raise PluginConfigError(f"Entry point {qualified_name!r} is not a Plugin subclass")
    return loaded
