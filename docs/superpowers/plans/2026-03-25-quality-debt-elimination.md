# Quality Debt Elimination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository pass `ruff check src tests` and `mypy src` cleanly (no pre-existing lint/type debt).

**Architecture:** Use a two-lane approach:
1. Eliminate **ruff** debt first using safe auto-fixes and targeted manual fixes by rule code.
2. Eliminate **mypy** debt next by addressing error categories in a type-stable order (generics first, then return typing, then union narrowing, then any/no-return cleanup).

Avoid config changes. Treat `ruff` and `mypy` runs as the primary "test" signals. After both lanes reach zero (Ruff + Mypy), run the full pytest suite to ensure behavior stability.

**Tech Stack:** `ruff`, `mypy`, `pytest`, Python 3.12.

---

## Assumptions / Non-Goals
- Do NOT change `pyproject.toml` ruff/mypy strictness unless explicitly required by an identified bug in tooling; if needed, document and isolate.
- Do NOT "paper over" issues with broad `# type: ignore` except where a precise narrow justification is documented in-code.
- Do NOT refactor large subsystems; prefer local typing/structure fixes that keep behavior unchanged.
- Focus on elimination of the *current* debt (the current error inventory at plan creation time). If error inventory changes after codebase evolution, re-run inventory and update tasks accordingly.
- Requires `rg` (ripgrep) for grepping mypy output in the example commands; if `rg` is unavailable, use `grep -E` equivalents.

---

## Inventory to Start From (Capture Again Before Fixing)

Run the following and store outputs under `docs/superpowers/plans/artifacts/`:

```bash
mkdir -p docs/superpowers/plans/artifacts/quality-debt-elimination/2026-03-25
.venv/bin/ruff check src tests --output-format=concise > docs/superpowers/plans/artifacts/quality-debt-elimination/2026-03-25/ruff.txt || true
.venv/bin/ruff check src tests --output-format=json > docs/superpowers/plans/artifacts/quality-debt-elimination/2026-03-25/ruff.json || true
.venv/bin/mypy src --show-error-codes --no-error-summary > docs/superpowers/plans/artifacts/quality-debt-elimination/2026-03-25/mypy.txt || true
```

Also record unique failing files:
```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
rf=Path("docs/superpowers/plans/artifacts/quality-debt-elimination/2026-03-25/ruff.json")
myp=Path("docs/superpowers/plans/artifacts/quality-debt-elimination/2026-03-25/mypy.txt")
jj=json.loads(rf.read_text())
ruff_files=sorted({v["filename"] for v in jj if isinstance(v, dict) and v.get("filename")})
print("Ruff failing files:", len(ruff_files))
for f in ruff_files: print(f)

import re
text=myp.read_text()
paths=set()
pat=re.compile(r'^([^:]+):(\d+)(?::\d+)?:\s+error:\s+.*\[(.*?)\]')
for line in text.splitlines():
    m=pat.match(line)
    if m:
        paths.add(m.group(1))
print("Mypy failing files:", len(paths))
for p in sorted(paths): print(p)
PY
```

---

## Lane 1: Ruff Debt Elimination

### Task 1: Safe ruff auto-fix sweep

**Files (global):**
- Modify: any files updated by ruff safe fixes across the current ruff-failing set.

**Test:**
- `ruff check src tests` must exit 0.

- [ ] Step 1: Run ruff baseline (EXPECTED: FAIL)

Run:
```bash
.venv/bin/ruff check src tests
```

Expected: non-zero exit code.

- [ ] Step 2: Apply safe auto-fixes (NO unsafe fixes)

Run:
```bash
.venv/bin/ruff check src tests --fix
```

Expected: may exit non-zero if not all violations can be auto-fixed. Do not treat a non-zero exit here as a failure; re-check in Step 3 and proceed lane-by-lane.

- [ ] Step 3: Re-run ruff to locate remaining debt (EXPECTED: FAIL until resolved)

Run:
```bash
.venv/bin/ruff check src tests --output-format=concise
```

- [ ] Step 4: Commit ruff auto-fix batch

Run:
```bash
git add -A
git commit -m "fix: reduce ruff debt via safe auto-fixes"
```

---

### Task 2: Eliminate ruff rule code `F401` (unused imports)

**Files (from current inventory at plan creation time):**
- Modify:
  - `src/syndicateclaw/audit/dead_letter.py`
  - `src/syndicateclaw/audit/integrity.py`
  - `src/syndicateclaw/audit/ledger.py`
  - `src/syndicateclaw/audit/service.py`
  - `src/syndicateclaw/db/models.py`
  - `src/syndicateclaw/db/repository.py`
  - `src/syndicateclaw/memory/service.py`
  - `src/syndicateclaw/memory/trust.py`
  - `src/syndicateclaw/orchestrator/snapshots.py`
  - `src/syndicateclaw/security/api_keys.py`
  - `tests/conftest.py`
  - `tests/scenarios/test_hostile_exercise.py`
  - `tests/unit/test_authz.py`
  - `tests/unit/test_boundary_controls.py`
  - `tests/unit/test_enforcement.py`
  - `tests/unit/test_final_fixes.py`
  - `tests/unit/test_hardening.py`
  - `tests/unit/test_release_gate.py`
  - `tests/unit/test_tightening.py`
  - `tests/unit/test_tools.py`
  - `tests/unit/test_upgrades.py`

- [ ] Step 1: Run targeted ruff selection (EXPECTED: FAIL)

Run:
```bash
.venv/bin/ruff check src tests --select F401 --output-format=concise
```

Expected: FAIL and show unused imports.

- [ ] Step 2: Implement minimal fixes

For each flagged occurrence:
1. Remove genuinely unused imports.
2. If an import is needed for side effects, replace with an explicit, justified side-effect import (and add a local comment).

- [ ] Step 3: Re-run targeted ruff selection (EXPECTED: PASS)

Run:
```bash
.venv/bin/ruff check src tests --select F401
```

- [ ] Step 4: Commit

Run:
```bash
git add -A
git commit -m "fix: remove unused imports (F401)"
```

---

### Task 3: Eliminate ruff rule code `E501` (line too long)

**Files (from current inventory at plan creation time):**
- Modify:
  - `src/syndicateclaw/api/routes/policy.py`
  - `src/syndicateclaw/api/routes/workflows.py`
  - `src/syndicateclaw/approval/service.py`
  - `src/syndicateclaw/audit/dead_letter.py`
  - `src/syndicateclaw/audit/export.py`
  - `src/syndicateclaw/audit/ledger.py`
  - `src/syndicateclaw/audit/service.py`
  - `src/syndicateclaw/authz/evaluator.py`
  - `src/syndicateclaw/authz/shadow_middleware.py`
  - `src/syndicateclaw/config.py`
  - `src/syndicateclaw/db/models.py`
  - `src/syndicateclaw/inference/metrics.py`
  - `src/syndicateclaw/memory/trust.py`
  - `src/syndicateclaw/models.py`
  - `src/syndicateclaw/policy/engine.py`
  - `src/syndicateclaw/tools/executor.py`
  - `tests/scenarios/test_hostile_exercise.py`
  - `tests/unit/test_authz.py`
  - `tests/unit/test_enforcement.py`
  - `tests/unit/test_hardening.py`
  - `tests/unit/test_orchestrator.py`
  - `tests/unit/test_release_gate.py`

- [ ] Step 1: Run targeted ruff selection (EXPECTED: FAIL)

Run:
```bash
.venv/bin/ruff check src tests --select E501 --output-format=concise
```

- [ ] Step 2: Fix line breaks without changing logic

Use:
1. Parenthesized multi-line expressions.
2. Extract long literals into named constants where appropriate.

- [ ] Step 3: Re-run targeted ruff selection (EXPECTED: PASS)

Run:
```bash
.venv/bin/ruff check src tests --select E501
```

- [ ] Step 4: Commit

Run:
```bash
git add -A
git commit -m "fix: wrap long lines to satisfy E501"
```

---

### Task 4: Eliminate ruff rule code `I001` (unsorted imports)

**Files (from current inventory at plan creation time):**
  - `src/syndicateclaw/approval/service.py`
  - `src/syndicateclaw/audit/export.py`
  - `src/syndicateclaw/audit/integrity.py`
  - `src/syndicateclaw/audit/service.py`
  - `src/syndicateclaw/db/repository.py`
  - `src/syndicateclaw/orchestrator/engine.py`
  - `tests/scenarios/test_hostile_exercise.py`
  - `tests/unit/test_authz.py`
  - `tests/unit/test_boundary_controls.py`
  - `tests/unit/test_enforcement.py`
  - `tests/unit/test_final_fixes.py`
  - `tests/unit/test_hardening.py`
  - `tests/unit/test_orchestrator.py`
  - `tests/unit/test_release_gate.py`
  - `tests/unit/test_tightening.py`
  - `tests/unit/test_upgrades.py`

- [ ] Step 1: Run targeted ruff selection (EXPECTED: FAIL)

Run:
```bash
.venv/bin/ruff check src tests --select I001 --output-format=concise
```

- [ ] Step 2: Fix imports

Prefer `ruff` import sorting. If needed:
1. Run `ruff check <files> --fix --select I001`.
2. Ensure import blocks stay logically grouped (stdlib/third-party/local).

- [ ] Step 3: Re-run targeted ruff selection (EXPECTED: PASS)

Run:
```bash
.venv/bin/ruff check src tests --select I001
```

- [ ] Step 4: Commit

Run:
```bash
git add -A
git commit -m "fix: sort imports (I001)"
```

---

### Task 5: Eliminate ruff rule code `B008` (function call in default argument)

**Files (from current inventory at plan creation time):**
  - `src/syndicateclaw/api/routes/approvals.py`
  - `src/syndicateclaw/api/routes/audit.py`
  - `src/syndicateclaw/api/routes/memory.py`
  - `src/syndicateclaw/api/routes/policy.py`
  - `src/syndicateclaw/api/routes/tools.py`
  - `src/syndicateclaw/api/routes/workflows.py`

- [ ] Step 1: Run targeted ruff selection (EXPECTED: FAIL)

Run:
```bash
.venv/bin/ruff check src tests --select B008 --output-format=concise
```

- [ ] Step 2: Fix by moving defaults inside functions

For each occurrence:
1. Replace `def f(x=Depends(...))` / `def f(x=some_call())` patterns.
2. Move the call to inside the function body or use a module-level singleton constant.
3. Preserve runtime behavior (do not change how FastAPI dependencies resolve).

- [ ] Step 3: Re-run targeted ruff selection (EXPECTED: PASS)

Run:
```bash
.venv/bin/ruff check src tests --select B008
```

- [ ] Step 4: Commit

Run:
```bash
git add -A
git commit -m "fix: remove function calls from default arguments (B008)"
```

---

### Task 6: Eliminate remaining small ruff codes (one rule family per task)

Run each rule code with targeted selection and fix. Use the current failing inventory as starting points:

- [ ] Step 1: Print remaining ruff errors (EXPECTED: FAIL)

Run:
```bash
.venv/bin/ruff check src tests --output-format=concise
```

- [ ] Step 2: For each remaining code, fix as follows (re-run after each code)

Codes and known current failing file sets:
1. `UP017` datetime-timezone-utc:
   - `src/syndicateclaw/db/base.py`
   - `src/syndicateclaw/db/models.py`
   - `src/syndicateclaw/db/repository.py`
   - `tests/unit/test_authz.py`
2. `UP038` non-pep604-isinstance:
   - `src/syndicateclaw/tools/executor.py`
3. `A002` builtin-argument-shadowing:
   - `src/syndicateclaw/db/repository.py`
4. `N801` invalid-class-name:
   - `tests/scenarios/test_hostile_exercise.py`
5. `SIM102` collapsible-if:
   - `src/syndicateclaw/tools/executor.py`
6. `SIM105` suppressible-exception:
   - `src/syndicateclaw/authz/shadow_middleware.py`
7. `B017` assert-raises-exception:
   - `tests/unit/test_upgrades.py`
8. `B904` raise-without-from-inside-except:
   - `src/syndicateclaw/api/routes/tools.py`
9. `B007` unused-loop-control-variable:
   - `src/syndicateclaw/security/ssrf.py`
10. `F841` unused-variable:
   - `src/syndicateclaw/audit/ledger.py`
11. `SIM117` multiple-with-statements:
   - `tests/scenarios/test_hostile_exercise.py`
   - `tests/unit/test_hardening.py`

For each code:
1. Run `.venv/bin/ruff check src tests --select <CODE> --output-format=concise`
2. Implement minimal logic-preserving fixes.
3. Re-run `.venv/bin/ruff check src tests --select <CODE>` (EXPECTED: PASS).
4. Commit after each code family:
   ```bash
   git add -A && git commit -m "fix: ruff <CODE> debt"
   ```

---

### Task 7: Ruff completion gate

- [ ] Step 1: Run full ruff check (EXPECTED: PASS)

Run:
```bash
.venv/bin/ruff check src tests
```

- [ ] Step 2: Run runtime-only tests as a quick sanity check (EXPECTED: PASS)

Run:
```bash
.venv/bin/pytest tests/runtime/ -q
```

- [ ] Step 3: Commit final ruff cleanup if needed

Run:
```bash
git add -A && git commit -m "fix: complete ruff debt elimination"
```

---

## Lane 2: Mypy Debt Elimination

### Task 8: Mypy baseline capture and error categorization

**Files (global):**
- Create artifacts under `docs/superpowers/plans/artifacts/quality-debt-elimination/2026-03-25/`.

- [ ] Step 1: Run mypy baseline (EXPECTED: FAIL)

Run:
```bash
.venv/bin/mypy src --show-error-codes --no-error-summary
```

- [ ] Step 2: Re-run with `--error-summary` to keep a count reference

Run:
```bash
.venv/bin/mypy src --show-error-codes
```

- [ ] Step 3: Commit the baseline artifacts (optional, but recommended)

Run:
```bash
git add docs/superpowers/plans/artifacts/quality-debt-elimination/2026-03-25/mypy.txt
git commit -m "chore: capture mypy debt baseline"
```

---

### Task 9: Fix missing generic type parameters (`[type-arg]`)

**Files (from current inventory at plan creation time, grouped by `[type-arg]`):**
- Modify (initial candidate set):
  - `src/syndicateclaw/approval/authority.py`
  - `src/syndicateclaw/approval/service.py`
  - `src/syndicateclaw/audit/dead_letter.py`
  - `src/syndicateclaw/audit/export.py`
  - `src/syndicateclaw/audit/integrity.py`
  - `src/syndicateclaw/audit/ledger.py`
  - `src/syndicateclaw/audit/service.py`
  - `src/syndicateclaw/channels/__init__.py`
  - `src/syndicateclaw/channels/console.py`
  - `src/syndicateclaw/channels/webhook.py`
  - `src/syndicateclaw/db/base.py`
  - `src/syndicateclaw/inference/metrics.py`
  - `src/syndicateclaw/inference/catalog_sync/fetch.py`
  - `src/syndicateclaw/inference/idempotency_payload.py`
  - `src/syndicateclaw/inference/catalog_sync/ssrf.py`
  - `src/syndicateclaw/memory/service.py`
  - `src/syndicateclaw/memory/trust.py`
  - `src/syndicateclaw/security/api_keys.py`
  - `src/syndicateclaw/audit/integrity.py`

**Strategy:** For each `[type-arg]`:
1. Prefer precise types (e.g., `dict[str, Any]`, `dict[str, str]`, `async_sessionmaker[AsyncSession]`).
2. If precision is hard, use `Any` narrowly in local variable scope rather than globally.

- [ ] Step 1: Run targeted mypy selection (EXPECTED: FAIL)

Run:
```bash
.venv/bin/mypy src --show-error-codes --no-error-summary | rg '\\[type-arg\\]'
```

Expected: FAIL overall; `rg` should output one or more `[type-arg]` lines.

Note: This isolates *reporting* only. MyPy may still be failing due to other error codes; do not wait for full mypy PASS until `[type-arg]` is eliminated.

```bash
.venv/bin/mypy src --show-error-codes --no-error-summary | rg '\\[type-arg\\]'
```

- [ ] Step 2: Implement typing fixes in small batches

Process by file:
1. Update one file.
2. Re-run mypy on that file with `--follow-imports=skip` if needed for speed.

Example:
```bash
.venv/bin/mypy src/syndicateclaw/channels/__init__.py --show-error-codes --no-error-summary
```

- [ ] Step 3: Re-run full mypy until `[type-arg]` is gone

Run:
```bash
.venv/bin/mypy src --show-error-codes --no-error-summary
```

Expected: mypy may still exit non-zero due to other remaining errors, but the output should contain zero `[type-arg]` matches.

- [ ] Step 4: Commit per batch

Run:
```bash
git add -A && git commit -m "fix: resolve mypy missing generic type parameters (type-arg)"
```

---

### Task 10: Fix missing annotations (`[no-untyped-def]`, `[no-untyped-call]`)

**Files (from current inventory):**
- Modify:
  - `src/syndicateclaw/api/main.py`
  - `src/syndicateclaw/authz/route_registry.py`
  - `src/syndicateclaw/api/routes/approvals.py`
  - `src/syndicateclaw/api/routes/policy.py`
  - `src/syndicateclaw/api/routes/memory.py`
  - `src/syndicateclaw/api/routes/inference.py`
  - `src/syndicateclaw/api/routes/audit.py`
  - `src/syndicateclaw/api/routes/providers_ops.py`

**Strategy:** Add:
- explicit return types for flagged functions
- explicit parameter types where mypy demands them

- [ ] Step 1: Run targeted mypy grep for `[no-untyped-def]`

Run:
```bash
.venv/bin/mypy src --show-error-codes --no-error-summary | rg '\\[no-untyped-(def|call)\\]'
```

- [ ] Step 2: Add annotations without changing runtime behavior

For each flagged function:
1. Determine the actual return type from code paths.
2. Add return annotations and any required param annotations.

- [ ] Step 3: Re-run mypy

Run:
```bash
.venv/bin/mypy src --show-error-codes --no-error-summary
```

- [ ] Step 4: Commit

Run:
```bash
git add -A && git commit -m "fix: add missing mypy annotations (no-untyped-def/no-untyped-call)"
```

---

### Task 11: Fix attribute availability errors (`[attr-defined]`)

**Files (from current inventory):**
- Modify:
  - `src/syndicateclaw/audit/dead_letter.py`
  - `src/syndicateclaw/audit/events.py`
  - `src/syndicateclaw/audit/ledger.py`
  - `src/syndicateclaw/inference/service.py`
  - `src/syndicateclaw/orchestrator/snapshots.py`

**Strategy:**
1. Where an attribute is conditionally present, refactor to initialize it always, or guard access.
2. Where a typing issue arises due to dataclass/base class fields, add accurate type definitions or `TypedDict`/`Protocol`.

- [ ] Step 1: Run targeted mypy

Run:
```bash
.venv/bin/mypy src --show-error-codes --no-error-summary | rg '\\[attr-defined\\]'
```

- [ ] Step 2: Implement attribute fixes file-by-file

For each file:
```bash
.venv/bin/mypy src/<path> --show-error-codes --no-error-summary
```

- [ ] Step 3: Commit per file batch

Run:
```bash
git add -A && git commit -m "fix: resolve mypy attr-defined"
```

---

### Task 12: Fix union attribute problems (`[union-attr]`)

**Files:**
- `src/syndicateclaw/policy/engine.py`
- `src/syndicateclaw/security/signing.py`

**Strategy:**
1. Introduce explicit `isinstance(...)` checks or pattern-match on union discriminators.
2. Use typing `cast(...)` only after the guard is proven.
3. Prefer small helper functions that return a narrowed type.

- [ ] Step 1: Run targeted mypy grep

Run:
```bash
.venv/bin/mypy src --show-error-codes --no-error-summary | rg '\\[union-attr\\]'
```

- [ ] Step 2: Implement narrowing

Update the specific failing expressions by guarding on the union variant.

- [ ] Step 3: Re-run mypy and commit

Run:
```bash
.venv/bin/mypy src --show-error-codes --no-error-summary
git add -A && git commit -m "fix: resolve mypy union-attr via narrowing"
```

---

### Task 13: Fix `no-any-return` issues (`[no-any-return]`)

**Files (from current top set):**
- `src/syndicateclaw/api/dependencies.py`
- `src/syndicateclaw/api/routes/inference.py`
- `src/syndicateclaw/audit/ledger.py`
- `src/syndicateclaw/authz/evaluator.py`
- `src/syndicateclaw/authz/shadow_middleware.py`
- `src/syndicateclaw/orchestrator/snapshots.py`
- `src/syndicateclaw/policy/engine.py`
- `src/syndicateclaw/security/api_keys.py`
- `src/syndicateclaw/security/auth.py`
- `src/syndicateclaw/tools/executor.py`

**Strategy:**
1. If a return path can be typed precisely, do so and stop returning `Any`.
2. If a return path is truly dynamic, introduce a conversion/normalization function and type it.
3. Use `cast` only as last resort after normalization.

- [ ] Step 1: Grep current mypy errors

Run:
```bash
.venv/bin/mypy src --show-error-codes --no-error-summary | rg '\\[no-any-return\\]'
```

- [ ] Step 2: Implement normalizations (one file at a time)
- [ ] Step 3: Re-run mypy and commit

---

### Task 14: Fix remaining mismatches (`[arg-type]`, `[call-arg]`, `[return-value]`, `[assignment]`, `[operator]`, `[index]`)

Process in order of smallest blast radius:
1. `[index]` (likely incorrect `None` guard)
2. `[assignment]` (initialization/optional counters)
3. `[return-value]` (return typing mismatches)
4. `[arg-type]` / `[call-arg]` (signature mismatch)
5. `[operator]` / other low frequency

**Files (current inventory examples):**
- `src/syndicateclaw/orchestrator/engine.py` (`[index]`, unused ignore)
- `src/syndicateclaw/inference/metrics.py` (`[assignment]`)
- `src/syndicateclaw/inference/catalog_sync/ssrf.py` (`[arg-type]`)
- `src/syndicateclaw/security/signing.py` (`[call-arg]`)
- `src/syndicateclaw/api/main.py` / `src/syndicateclaw/audit/service.py` / `src/syndicateclaw/audit/ledger.py` (`[return-value]`)
- `src/syndicateclaw/audit/integrity.py` (`[operator]`)

- [ ] Step 1: Identify exact current error list

Run:
```bash
.venv/bin/mypy src --show-error-codes --no-error-summary > docs/superpowers/plans/artifacts/quality-debt-elimination/2026-03-25/mypy.remaining.txt || true
```

- [ ] Step 2: Fix the smallest group first, re-run mypy after each file change

For each file:
```bash
.venv/bin/mypy src/<path> --show-error-codes --no-error-summary
```

- [ ] Step 3: Commit

Run:
```bash
git add -A && git commit -m "fix: resolve remaining mypy mismatches"
```
 
---

### Task 15: Mypy completion gate

- [ ] Step 1: Run mypy until zero (EXPECTED: PASS)

Run:
```bash
.venv/bin/mypy src --show-error-codes
```

- [ ] Step 2: Run full pytest suite (EXPECTED: PASS)

Run:
```bash
.venv/bin/pytest -q
```

- [ ] Step 3: Commit completion

Run:
```bash
git add -A && git commit -m "fix: eliminate mypy debt and verify tests"
```

---

## Phase 3: CI / Regression Safety Checks

### Task 16: Ensure runtime Phase 1 gates still pass

- [ ] Step 1: Run runtime-only tests

Run:
```bash
.venv/bin/pytest tests/runtime/ -q
```

- [ ] Step 2: Run runtime schema export (EXPECTED: no diffs)

Run:
```bash
# Phase 1 expectations are documented in `docs/superpowers/specs/runtime-phase1.md`.
.venv/bin/python -m syndicateclaw.runtime.contracts.export_schemas
git diff --exit-code -- src/syndicateclaw/runtime/contracts/jsonschema/
```

- [ ] Step 3: Commit if artifacts changed (should not)

---

## Execution Handoff Options

Plan complete and saved to `docs/superpowers/plans/2026-03-25-quality-debt-elimination.md`.

Two execution options:

1. Subagent-Driven (recommended) - Use superpowers:subagent-driven-development with a fresh subagent per task, review between tasks.
2. Inline Execution - Use superpowers:executing-plans to run the tasks with checkpoints.

Which approach?

