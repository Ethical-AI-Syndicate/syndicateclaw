# ADR-0010: Namespace-based multi-tenancy

**Status:** Accepted  
**Date:** 2026-03-27

## Context

Enterprise deployments need tenant isolation without per-tenant databases at small scale.

## Decision

Resources carry a `namespace` column enforced NOT NULL after backfill; org maps to namespace.

## Consequences

Cross-namespace access requires explicit impersonation with audit, not implicit admin bypass.

## Alternatives Considered

Database-per-tenant (deferred for operational cost).
