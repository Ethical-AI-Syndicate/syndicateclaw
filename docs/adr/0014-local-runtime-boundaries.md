# ADR-0014: LocalRuntime security boundaries

**Status:** Accepted  
**Date:** 2026-03-27

## Context

Developers want a fast local loop without standing up the full control plane.

## Decision

`LocalRuntime` is blocked in production-like environments and emits explicit warnings listing bypassed controls.

## Consequences

Production paths must use the hosted engine with RBAC, policy, and audit.

## Alternatives Considered

Silent local execution (rejected).
