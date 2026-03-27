# ADR-0008: PostgreSQL queue for agent messages

**Status:** Accepted  
**Date:** 2026-03-27

## Context

Agent mesh messaging needs persistence without operating a separate broker in small deployments.

## Decision

Messages are stored in PostgreSQL with background delivery workers.

## Consequences

Throughput is bounded by DB polling; large installs may add external brokers later.

## Alternatives Considered

NATS/RabbitMQ as mandatory dependencies (deferred).
