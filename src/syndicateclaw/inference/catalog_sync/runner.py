"""Fetch models.dev JSON (SSRF-safe) and merge into ModelCatalog with audit + metrics."""

from __future__ import annotations

from typing import Any

import httpx
import structlog
from ulid import ULID

from syndicateclaw.inference.catalog import ModelCatalog
from syndicateclaw.inference.catalog_sync.errors import ModelsDevFetchError, SSRFBlockedError
from syndicateclaw.inference.catalog_sync.fetch import fetch_https_bytes_bounded
from syndicateclaw.inference.catalog_sync.modelsdev import (
    ModelsDevCatalogSync,
    ModelsDevSyncResult,
    parse_models_dev_json,
)
from syndicateclaw.inference.config_schema import ProviderSystemConfig
from syndicateclaw.inference.metrics import record_catalog_sync_models_dev_outcome
from syndicateclaw.models import AuditEvent, AuditEventType

logger = structlog.get_logger(__name__)


async def run_models_dev_catalog_sync(
    *,
    feed_url: str,
    allowed_host_suffixes: tuple[str, ...],
    max_bytes: int,
    timeout_seconds: float,
    max_redirects: int,
    catalog: ModelCatalog,
    base_system_config: ProviderSystemConfig,
    audit_service: Any,
    actor: str,
    trace_id: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ModelsDevSyncResult:
    """Fetch → parse → merge. Preserves previous catalog on fetch/parse/anomaly failure."""
    tid = trace_id or str(ULID())
    allowed_ids = frozenset(p.id for p in base_system_config.providers)
    syncer = ModelsDevCatalogSync(
        base_system_config=base_system_config,
        allowed_provider_ids=allowed_ids,
        catalog=catalog,
        yaml_static_rows=base_system_config.static_catalog,
        yaml_wins_on_key_collision=base_system_config.catalog_coexistence.yaml_wins_on_key_collision,
    )

    await audit_service.emit(
        AuditEvent(
            event_type=AuditEventType.CATALOG_SYNC_STARTED,
            actor=actor,
            resource_type="catalog",
            resource_id="models_dev",
            action="sync",
            trace_id=tid,
            details={"feed_url": feed_url[:512]},
        )
    )

    try:
        raw = await fetch_https_bytes_bounded(
            url=feed_url,
            allowed_host_suffixes=allowed_host_suffixes,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
            max_redirects=max_redirects,
            transport=transport,
        )
    except SSRFBlockedError as e:
        logger.warning("catalog_sync.ssrf_blocked", error=str(e))
        record_catalog_sync_models_dev_outcome("ssrf_blocked")
        await _emit_failed(audit_service, actor, tid, "ssrf_blocked", str(e))
        return ModelsDevSyncResult(
            applied=False,
            snapshot_version=catalog.snapshot_version,
            records_accepted=0,
            records_skipped=0,
            aborted_reason="ssrf_blocked",
        )
    except ModelsDevFetchError as e:
        logger.warning("catalog_sync.fetch_failed", error=str(e))
        record_catalog_sync_models_dev_outcome("fetch_failed")
        await _emit_failed(audit_service, actor, tid, "fetch_failed", str(e))
        return ModelsDevSyncResult(
            applied=False,
            snapshot_version=catalog.snapshot_version,
            records_accepted=0,
            records_skipped=0,
            aborted_reason="fetch_failed",
        )
    except Exception as e:
        logger.exception("catalog_sync.fetch_unexpected")
        record_catalog_sync_models_dev_outcome("fetch_failed")
        await _emit_failed(audit_service, actor, tid, "fetch_failed", str(e))
        return ModelsDevSyncResult(
            applied=False,
            snapshot_version=catalog.snapshot_version,
            records_accepted=0,
            records_skipped=0,
            aborted_reason="fetch_failed",
        )

    try:
        text = raw.decode("utf-8")
        records = parse_models_dev_json(text)
    except (UnicodeDecodeError, ValueError) as e:
        record_catalog_sync_models_dev_outcome("parse_failed")
        await _emit_failed(audit_service, actor, tid, "parse_failed", str(e))
        return ModelsDevSyncResult(
            applied=False,
            snapshot_version=catalog.snapshot_version,
            records_accepted=0,
            records_skipped=0,
            aborted_reason="parse_failed",
        )

    snap = str(ULID())
    prev_count = catalog.entry_count
    result = syncer.sync_from_parsed_records(
        records,
        snapshot_version=snap,
        previous_count=prev_count,
    )

    if not result.applied and result.aborted_reason == "systemic_anomaly_drop":
        record_catalog_sync_models_dev_outcome("anomaly_aborted")
        await audit_service.emit(
            AuditEvent(
                event_type=AuditEventType.CATALOG_SYNC_ANOMALY_ABORTED,
                actor=actor,
                resource_type="catalog",
                resource_id="models_dev",
                action="sync",
                trace_id=tid,
                details={
                    "aborted_reason": result.aborted_reason,
                    "records_skipped": result.records_skipped,
                    "snapshot_version": catalog.snapshot_version,
                },
            )
        )
        return result

    if result.applied:
        record_catalog_sync_models_dev_outcome("success")
        await audit_service.emit(
            AuditEvent(
                event_type=AuditEventType.CATALOG_SYNC_COMPLETED,
                actor=actor,
                resource_type="catalog",
                resource_id="models_dev",
                action="sync",
                trace_id=tid,
                details={
                    "snapshot_version": result.snapshot_version,
                    "records_accepted": result.records_accepted,
                    "records_skipped": result.records_skipped,
                },
            )
        )

    return result


async def _emit_failed(
    audit_service: Any,
    actor: str,
    trace_id: str,
    reason: str,
    detail: str,
) -> None:
    await audit_service.emit(
        AuditEvent(
            event_type=AuditEventType.CATALOG_SYNC_FAILED,
            actor=actor,
            resource_type="catalog",
            resource_id="models_dev",
            action="sync",
            trace_id=trace_id,
            details={"reason": reason, "detail": detail[:2000]},
        )
    )
