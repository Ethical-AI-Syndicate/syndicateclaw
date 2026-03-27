# ADR-0013: Streaming tokens for SSE and builder

**Status:** Accepted  
**Date:** 2026-03-27

## Context

Primary JWTs must not appear in URLs or logs for SSE or visual builder saves.

## Decision

Short-lived streaming tokens gate `/runs/{id}/stream`; multi-use builder tokens gate workflow PUT with `X-Builder-Token`.

## Consequences

Clients must refresh streaming tokens on reconnect; builder sessions rely on header auth for writes.

## Alternatives Considered

Primary JWT as query parameter (rejected).
