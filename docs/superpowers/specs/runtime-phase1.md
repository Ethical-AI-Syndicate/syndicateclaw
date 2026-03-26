# SyndicateClaw Skill Runtime — Phase 1 Specification

**Status:** Implemented (internal control plane)  
**Scope:** Manifest validation, filesystem-backed registry, deterministic routing, single-skill execution, mandatory audit records — **no** public HTTP routes, **no** planner or multi-step automation.

**What this is not:** This is **not** a full agent runtime. It is a **bounded skill execution control plane**: contracts, registry, routing, execution, and audit — suitable for governance and replay **before** tool gateway hardening, policy adapters, memory adapters, or planners.

## Intent

Phase 1 delivers a **separate runtime control plane** for skills that is additive to the existing FastAPI surface, workflow engine, inference router, tools, memory, and policy subsystems. It does **not** rename or extend `InferenceRouter` (provider/model routing remains distinct).

## Package layout

| Path | Responsibility |
|------|----------------|
| `src/syndicateclaw/runtime/contracts/` | Pydantic v2 models + JSON Schema export under `contracts/jsonschema/` |
| `src/syndicateclaw/runtime/registry/` | Load and validate YAML/JSON manifests from disk; in-memory `SkillRegistry` |
| `src/syndicateclaw/runtime/router/` | Deterministic `SkillRouter.route_task` with `UNCERTAIN` on ties |
| `src/syndicateclaw/runtime/execution/` | `ExecutionEngine.execute_skill` — JSON Schema I/O validation, handler protocol, `ToolInvoker` |
| `src/syndicateclaw/runtime/audit/` | `AuditSink` protocol; `InMemoryAuditSink` for tests |

## What “deterministic” means here

| Area | Behavior |
|------|----------|
| **Registry load** | Manifest paths are enumerated with `sorted(directory.iterdir())` — lexicographic, OS-independent for a given directory snapshot. **Load order does not change** the resolved registry after a successful load: indexes are built from the **set** of manifests sorted by `(skill_id, packaging.version.Version)`. |
| **Duplicate detection** | Same `(skill_id, version)` in two files → `RegistryLoadError` (which duplicate is reported first follows sorted path order). |
| **Latest resolution** | `SkillRegistry.get(skill_id)` uses `max(..., key=Version)` — **PEP 440 / packaging** semantics, including prereleases and local segments. |
| **Routing** | Same `TaskContext` + same registry snapshot → same `RoutingDecision` (see `normalize_goal`: NFC, lowercase, strip). |
| **No randomness** | Router uses no RNG and no wall-clock. |

## Fail-closed conditions

- Unknown skill id/version at registry resolution → `UnknownSkillError`.
- Invalid or duplicate manifest on load → `ManifestValidationError` / `RegistryLoadError`.
- Ambiguous routing (tie on trigger score, risk, determinism) → `RoutingStatus.UNCERTAIN`, **no** selected skill.
- `non_triggers` → **hard exclusion** (not a score penalty): if any phrase matches, the skill is removed from candidates.
- Skill ref mismatch, invalid I/O vs manifest JSON Schema, missing handler, or tool authorization failure → `ExecutionRecord` with `FAILED` and **audit append attempted**.
- **Audit sink append failure** → `AuditSinkError` raised: the overall operation **fails** even if handler logic completed successfully. For governance-first semantics, **persisted audit evidence is part of success**; a broken sink is not a “successful” execution.
- **Tool policy:** `tool_policy: explicit_allowlist` with `allowed_tools: []` means **deny-all** (empty list). This is **not** the same as `tool_policy: deny_all`: the latter is an explicit author intent that **must** pair with an empty `allowed_tools` (validated at manifest load). Execution records include `manifest_tool_policy` and decision lines that distinguish **explicit deny-all** vs **empty allowlist**.

Handlers are **in-process Python**: Phase 1 does **not** sandbox imports. A malicious handler can bypass `ToolInvoker` by importing clients directly — **operational and review discipline** apply; enforcement moves to subprocess/sandbox or separate service in later phases.

## Substring routing (known limitations)

Phase 1 uses **substring** intent matching on the normalized goal. That implies:

- **Case** is folded (via `normalize_goal`).
- **Token boundaries are not enforced** — e.g. `echo` matches inside `echolocation`.
- **Punctuation** is not stripped; phrases are matched as literal substrings after normalization.

Upgrades (token-based, embeddings, or policy-gated overrides) belong in later phases — **not** silent `UNCERTAIN` fallbacks to “best effort” routing.

## Schema enforcement symmetry

- **Manifest shell** (`SkillManifest`) is validated by **Pydantic** at load time.
- **Handler I/O** is validated with the **embedded** `input_schema` / `output_schema` dicts using **jsonschema** Draft 2020-12 — the same dicts attached to the manifest, not a second copy.
- Exported JSON Schemas under `contracts/jsonschema/` are generated from the Pydantic models (`model_json_schema`) for **contract review and CI diff**; runtime I/O enforcement for payloads uses **manifest-embedded** schemas.

`additionalProperties`, nullability, and defaults follow **only** what those embedded schemas say.

## JSON Schema artifacts

```bash
python -m syndicateclaw.runtime.contracts.export_schemas
```

Outputs to `src/syndicateclaw/runtime/contracts/jsonschema/`. Tests re-export and validate consistency.

## Golden fixtures

Under `tests/runtime/fixtures/golden/`, committed JSON files define **stable** routing and execution snapshots for replay-style tests.

## Merge gate (recommended)

- Freeze Phase 1 contracts for one release cycle where possible.
- CI: run schema export and **fail on git diff** for `contracts/jsonschema/` (tests already exercise export).
- Keep golden execution/routing fixtures updated when behavior intentionally changes.

## Integration posture

- **Adapters later:** Existing platform services integrate through explicit adapters; Phase 1 avoids importing API handlers or workflow state as runtime memory.
- **Rollout:** Same discipline as RBAC shadow mode — internal package first, observation, enforcement, then any external exposure.

## Phase 2 — suggested order (enforcement before expansion)

1. Tool gateway hardening (adapter to existing tools, authorization logs, idempotency for mutating tools).
2. Policy engine adapter (pre/post hooks, decisions on `ExecutionRecord`).
3. Memory adapter (scoped, attributed writes).
4. Runtime replay harness against frozen manifests + golden fixtures.
5. **Only then** planner / multi-step execution.

## Deferred (not Phase 1)

- Planner, autonomous chaining, approval checkpoints.
- Public or admin HTTP endpoints for runtime APIs.
- Background automation loops.
- Coupling this router into `InferenceRouter`.
- Mutable process-wide registry singletons without explicit load order and versioning.
