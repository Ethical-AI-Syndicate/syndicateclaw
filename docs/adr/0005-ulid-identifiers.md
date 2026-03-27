# ADR-0005: ULID for identifiers

**Status:** Accepted  
**Date:** 2026-03-27

## Context

IDs must be unique, sortable by creation time, and URL-safe.

## Decision

Primary keys use ULID strings.

## Consequences

Lexicographic ordering approximates time ordering; migration from UUID possible with care.

## Alternatives Considered

UUID v4 only (rejected — weaker sort locality).
