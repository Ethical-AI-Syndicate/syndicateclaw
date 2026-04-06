# ADR-0006: Safe expression evaluator

**Status:** Accepted  
**Date:** 2026-03-27

## Context

Workflow conditions must not execute arbitrary Python.

## Decision

Conditions are parsed and evaluated by a dedicated safe evaluator, not `eval()`.

## Consequences

Expression language is intentionally limited; complex logic uses explicit nodes.

## Alternatives Considered

Embedded Python (rejected).
