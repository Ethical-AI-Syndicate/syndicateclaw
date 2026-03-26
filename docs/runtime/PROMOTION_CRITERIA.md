# Runtime module promotion criteria

The `runtime/` package is Phase 1 experimental. Before coupling it to the stable API surface:

1. **Isolation** — No imports from `runtime/` in `api/`, `orchestrator/`, `tools/`, `policy/`, `audit/`, `approval/`, `memory/`, `security/`, or `authz/` without an ADR.
2. **Flag** — `SYNDICATECLAW_RUNTIME_ENABLED` remains the gate for any runtime routes or startup hooks.
3. **CI** — `tests/runtime/` and contract schema jobs stay green; schema artifacts committed.
4. **Typing** — `mypy` clean for `src/syndicateclaw/runtime`.
