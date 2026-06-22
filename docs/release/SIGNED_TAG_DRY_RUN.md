# Signed-Tag Dry-Run (Local-Only)

**Spec ID:** SDD-GOV-SIGNTAG-001
**Status of this artifact:** specification + operator documentation
**Applies to:** `scripts/release/verify_release_provenance.py`,
`scripts/release/generate_release_manifest.py`, and the
`release_signed_tag_dry_run` CI job.

## Intent

Prove, without creating or pushing any production release tag, that the full
`--require-signed` verification path can verify **both**:

1. a signed release manifest (`manifest_signature_verified: true`), and
2. an annotated **signed tag** (`signed_tag_verified: true`).

This closes the gap left by the manifest-signing dry-run, which proves only the
manifest signature and leaves the tag advisory.

## Two distinct dry-runs (do not conflate)

| Job | Proves | Tag involved |
|---|---|---|
| `release_manifest_signing_dry_run` | A real protected GPG key signs the release **manifest** and the signature verifies. | None. Tag is advisory; `signed_tag_verified` is not asserted. |
| `release_signed_tag_dry_run` | The **full** `--require-signed` path: signed manifest **and** a cryptographically verified annotated signed tag whose signer matches the expected key. | A **local-only**, non-release, non-semver annotated signed tag that is created, verified, and deleted within the job. |

## Local-only tag semantics

The signed-tag dry-run creates an annotated signed tag named:

```
provenance-ci-test/<pipeline-id>/<short-sha>
```

This name is deliberately:

- **non-semver** — it cannot match `^v[0-9]` release/publish rules, so no
  release, publish, deploy, or `semantic-release`/`goreleaser` job can ever key
  off it;
- **clearly non-release** — the `provenance-ci-test/` prefix marks it as a proof
  artifact, not a version.

The tag is:

- created **locally only** with the protected GPG key (ephemeral `GNUPGHOME`);
- **never pushed** — the job asserts `git ls-remote --tags origin` does not
  contain it before completing;
- **deleted in a cleanup trap** on job exit (success or failure).

GitLab pipelines are triggered by pushes to the server, not by local git
operations inside a running job. A tag created locally and never pushed cannot
trigger any other pipeline, release, or deploy.

## Strengthened verifier behavior

`verify_release_provenance.py` no longer treats the mere textual presence of a
PGP signature block as a "signed tag". For an annotated tag it now runs
`git verify-tag` and:

- sets `signed_tag_verified: true` **only** when GnuPG reports a good, valid
  signature (`GOODSIG` + `VALIDSIG`) **and** — when `--expected-key-id` is
  supplied — the tag signer matches that key;
- records the tag signer under `tag_signer_key_id`;
- under `--require-signed`, a tag that fails cryptographic verification, or a
  signer that does not match the expected key, is a hard error (fail closed).

This **strengthens** `--require-signed`; it never weakens or bypasses it. The
signer's public key must be present in the verifying keyring at verification
time, which is the case in the dry-run (the key is imported) and is a
requirement of the real release environment.

## Why this is NOT a production release

- No production/semver release tag is created.
- No tag is pushed to any remote.
- No deploy, publish, or release job runs.
- The proof uses a throwaway/ephemeral keyring locally and the protected key
  only inside a manual, default-branch-only CI job.

A production release **still requires** an actual annotated signed release tag
(e.g. `vX.Y.Z`) created and verified under the real release workflow. This
dry-run proves the *verification path* works; it does not constitute a release
and does not prove production readiness.

## Constraints (enforced)

- No production release tags.
- No tag push.
- No production deploy.
- No exposure of signing keys, passphrases, or tokens (key import is done with
  shell tracing disabled; the ephemeral `GNUPGHOME` is always removed).
- `--require-signed` is not weakened and signed-tag verification is not bypassed.

## Verification plan

- Local: a throwaway passphrase-protected key proves the end-to-end path
  (unsigned advisory pass, `--require-signed` fail-closed on unsigned, signed-tag
  full verify pass, signer-key match, tag-not-pushed, tag cleanup).
- CI: `release_signed_tag_dry_run` is **manual** and runs only on the protected
  default branch (`main`), where the protected `GPG_*` variables are exposed. On
  any other ref it fails closed because the protected key is absent.

## Evidence boundary

- **Proves:** the verifier and generator can produce and cryptographically
  verify a signed manifest **and** a signed annotated tag under `--require-signed`,
  and that a local-only proof tag is never pushed and is cleaned up.
- **Does not prove:** that a production release has occurred, that the production
  release key is correctly provisioned in every release runner, or production
  readiness. Full signed release closure requires an authorized annotated signed
  release tag created and verified under the real release workflow.
