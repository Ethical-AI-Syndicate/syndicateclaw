# ADR-0012: Workflow versioning via separate table

**Status:** Accepted  
**Date:** 2026-03-27

## Context

Operators need immutable history and rollback without losing auditability.

## Decision

`workflow_versions` stores historical snapshots; rollback creates a new version row.

## Consequences

Storage grows with edits; archiving policy applies after cap.

## Alternatives Considered

Single JSONB blob with embedded history (rejected — harder to query and index).
