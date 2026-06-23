# Release & Deploy Flow Gating

**Spec ID:** SDD-GOV-SIGNTAG-001 (follow-up remediation)
**Branch of record:** `fix/claw-release-flow-gating`
**Status of this artifact:** operator documentation + policy specification
**Applies to:** `.gitlab-ci.yml` (`release`, `deploy_staging`, `deploy_production` jobs)
and `scripts/ci/check_release_deploy_gating.py`.

## Intent

Prevent an ordinary push to `main` from **automatically cutting a release tag** or
**automatically running a deploy**. An ordinary `fix:`/`feat:` merge to `main`
must produce validation, test, and build evidence — and nothing that mutates the
release surface or a running environment — unless an operator explicitly asks for
it.

This remediation was prompted by an **unintended** `v2.2.10` tag: `semantic-release`
ran on an ordinary `main` push and auto-cut a release tag from conventional
commits. See "Legacy `v2.2.10`" below — that tag is left intact; this change only
prevents recurrence.

## What "ordinary main push" means

```
CI_PIPELINE_SOURCE == "push"  AND  CI_COMMIT_BRANCH == "main"
  AND no release/deploy opt-in variable is set
  AND it is not a tag pipeline
```

Under that environment, **no** release-cutting, tag-creating, or deploy job may
run automatically (`when: on_success`/`always`/`delayed`). They must instead be
gated behind an explicit operator context or `when: manual`.

## Current gating (after this change)

| Job | Old trigger | New trigger | Auto on ordinary main push? |
|---|---|---|---|
| `release` (semantic-release) | `push` + `main` → `on_success` | `web` pipeline + `RELEASE == "true"` → `on_success`, else `never` | **No** |
| `deploy_staging` | `push` + `main` → `on_success` | `web` pipeline + `DEPLOY_STAGING == "true"` → `manual` (`allow_failure`), else `never` | **No** |
| `deploy_production` | `CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/` → `on_success` | unchanged (tag-gated, never keys off `main`) | **No** |

`deploy_production` was already tag-gated and is intentionally left unchanged: it
fires only on an explicit semver tag, never on a branch push.

## How to intentionally release or deploy

These flows are deliberately **operator-initiated** (a web-triggered pipeline with
a pipeline variable — `CI/CD → Pipelines → Run pipeline` in GitLab):

| Goal | Pipeline source | Variable | Resulting job |
|---|---|---|---|
| Cut a release | Run pipeline (web) on `main` | `RELEASE = true` | `release` runs `semantic-release` |
| Deploy to staging | Run pipeline (web) on `main` | `DEPLOY_STAGING = true` | `deploy_staging` becomes a manual button |
| Deploy to production | Push an annotated semver tag | — | `deploy_production` runs |

No environment variable or web pipeline is required for ordinary development: a
normal `main` merge still runs `validate`, tests, security, build, and the
release **gates** (`preprod_release_gate` etc.), which are evidence checks, not
release or deploy actions.

## CI enforcement

The `validate:release-deploy-gating` job (stage `validate`, runs on every MR and
on `main`) statically proves the policy holds. It runs
`scripts/ci/check_release_deploy_gating.py`, which:

1. parses `.gitlab-ci.yml`,
2. classifies each job as tag-creating (script contains `semantic-release`,
   `git tag`, or `goreleaser`) and/or deploy (name starts `deploy`, uses
   `kubectl`/`helm upgrade`, or declares an `environment`),
3. evaluates each such job's **first matching rule** under the ordinary-main-push
   environment, and
4. **fails the pipeline closed** if any of them would auto-run.

The check **never** runs a release or a deploy — it only inspects rules. It
ships a `--selftest` covering positive cases (auto-on-main, unconditional,
branch-only default `on_success` → all flagged) and negative cases (web+variable,
manual, tag-gated → all allowed), so the evaluator itself is exercised in CI.

## Legacy `v2.2.10`

`v2.2.10` was created before this gating existed. It is treated as **unintended
legacy** and is **left intact**: this remediation does **not** delete, rewrite, or
replace it, and creates **no** replacement or new release tag. Any decision about
`v2.2.10` is out of scope for this change.

## Relationship to signed-release closure (not proven here)

This change gates *when* a release may be cut; it does **not** establish signed
release provenance. `semantic-release` produces **lightweight, unsigned** tags,
which do **not** satisfy the `--require-signed` path documented in
[`SIGNED_TAG_DRY_RUN.md`](./SIGNED_TAG_DRY_RUN.md). Full signed-release closure
still requires an **annotated, signed** release tag verified by
`verify_release_provenance.py --require-signed`. That remains **not proven** for
ordinary releases and is future work tracked under SDD-GOV-SIGNTAG-001.

The signed-release flow that creates those annotated signed tags under explicit
release context is designed and CI-proven in dry-run in
[`SIGNED_RELEASE_FLOW.md`](./SIGNED_RELEASE_FLOW.md).

## What this proves / does not prove

**Proves:** on an ordinary `main` push, no release/tag-creating/deploy job
auto-runs, and CI enforces this on every MR and `main` pipeline.

**Does not prove:** that releases are signed; that production is deployable; that
`v2.2.10` is valid or should be retained; production readiness. Where evidence is
absent, it is marked "not proven."
