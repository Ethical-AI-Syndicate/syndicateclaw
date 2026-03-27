# ADR-0007: Provider abstraction

**Status:** Accepted  
**Date:** 2026-03-27

## Context

LLM and embedding calls must be swappable and centrally governed.

## Decision

All model calls go through `ProviderService` with YAML-driven configuration.

## Consequences

Keys stay out of workflow definitions; rate limits and audit attach at the service layer.

## Alternatives Considered

Direct vendor SDK calls from handlers (rejected).
