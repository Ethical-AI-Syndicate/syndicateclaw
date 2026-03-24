"""Protocol adapters — HTTP only; no routing or policy."""

from syndicateclaw.inference.adapters.base import ModelProvider
from syndicateclaw.inference.adapters.factory import adapter_for

__all__ = ["ModelProvider", "adapter_for"]
