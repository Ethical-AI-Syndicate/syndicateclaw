"""Built-in plugins (no-op or minimal side effects)."""

from syndicateclaw.plugins.builtin.audit_trail import AuditTrailPlugin
from syndicateclaw.plugins.builtin.webhook import WebhookPlugin

__all__ = ["AuditTrailPlugin", "WebhookPlugin"]
