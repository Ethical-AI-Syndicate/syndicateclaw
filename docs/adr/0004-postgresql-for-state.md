# ADR-0004: PostgreSQL for durable state

**Status:** Accepted  
**Date:** 2026-03-27

## Context

Workflows, RBAC, and audit require ACID durability and relational queries.

## Decision

PostgreSQL is the system of record for application state.

## Consequences

Horizontal scaling relies on connection pooling and read patterns, not embedded stores.

## Alternatives Considered

In-memory-only orchestration (rejected for production).
