# ADR-0003: Append-only audit log

**Status:** Accepted  
**Date:** 2026-03-27

## Context

Compliance and forensics require tamper-evident, append-only audit records.

## Decision

Audit events are inserted only; updates are not part of the public API.

## Consequences

Corrections are recorded as new events with references, not silent edits.

## Alternatives Considered

Mutable audit rows (rejected).
