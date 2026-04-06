# ADR-0011: Plugin sandbox

**Status:** Accepted  
**Date:** 2026-03-27

## Context

Third-party plugins must not exfiltrate data or spawn uncontrolled tasks.

## Decision

Plugins load only via entry points or `module:Class`; AST checks ban risky imports/calls; `PluginContext.state` is a `MappingProxyType` over a deep copy.

## Consequences

Malicious plugins are still a supply-chain risk; review and signing remain important.

## Alternatives Considered

Arbitrary `.py` paths (rejected).
