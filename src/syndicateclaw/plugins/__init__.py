"""Plugin system (v1.5.0)."""

from syndicateclaw.plugins.base import Plugin, PluginContext
from syndicateclaw.plugins.registry import PluginConfigError, PluginRegistry

__all__ = ["Plugin", "PluginContext", "PluginConfigError", "PluginRegistry"]
