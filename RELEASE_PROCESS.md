# Release Process

## Branching and tagging

Merge requests should run validate, unit/integration checks, migration checks, security scans, readiness checks, SBOM generation, dependency audit, and provenance evidence. Production promotion requires a semver tag or explicit `RELEASE_VERSION`.

## Evidence artifacts

- pytest/JUnit and coverage output
- migration check output
- readiness check output
- `sbom.spdx.json` or `sbom.cdx.json`
- `dependency-audit-report.json`
- `provenance-evidence.json`
- image digest and rendered Kubernetes manifests

## Approval roles

Pre-production approval requires engineering and customer platform owner. Production approval requires customer SRE/security/change owner.

## Emergency hotfix

Hotfixes require the same release evidence. Any skipped gate must have customer approval, expiry, and compensating control.

## Rollback

Rollback requires previous image digest, previous manifests, database backup/snapshot ID, migration rollback plan, and post-rollback health/audit checks.

## CI gates

Manual `preprod_release_gate` and `prod_release_gate` jobs run `scripts/release-gate-check.sh`. They do not deploy.
