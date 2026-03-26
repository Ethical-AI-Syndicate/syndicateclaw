"""Errors for catalog sync / models.dev fetch."""

from __future__ import annotations


class CatalogSyncError(Exception):
    """Base for catalog sync failures."""


class SSRFBlockedError(CatalogSyncError):
    """Resolved URL or address is not allowed (private, loopback, or policy)."""


class ModelsDevFetchError(CatalogSyncError):
    """HTTP fetch or size/redirect limits."""
