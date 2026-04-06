# ADR-0009: Scheduler with SKIP LOCKED

**Status:** Accepted  
**Date:** 2026-03-27

## Context

Multiple scheduler instances must not double-fire the same due schedule.

## Decision

Claims use `SELECT … FOR UPDATE SKIP LOCKED` with lease-based locks.

## Consequences

No separate distributed lock service required for correctness at modest scale.

## Alternatives Considered

Redis distributed locks only (rejected as sole mechanism).
