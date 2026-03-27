# ADR-0002: Fail-closed policy engine

**Status:** Accepted  
**Date:** 2026-03-27

## Context

Tool and workflow actions must be denied when policy evaluation cannot complete.

## Decision

Policy engine denies by default when rules are ambiguous or storage is unavailable.

## Consequences

Safer failures; operators must explicitly allow paths in policy.

## Alternatives Considered

Fail-open (rejected — unsafe for enterprise deployments).
