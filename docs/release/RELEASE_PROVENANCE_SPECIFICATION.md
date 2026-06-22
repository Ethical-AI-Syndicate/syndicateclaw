# AI Syndicate Release Provenance Specification

**Specification ID**: SDD-GOV-PROVENANCE-001  
**Schema Version**: 1.0.0

This document defines the release provenance and supply-chain integrity standard for all core AI Syndicate repositories.

## 1. Release Manifest Schema

Every release candidate must generate a `release_manifest.json` located at the repository root. The manifest must conform to the following schema:

```json
{
  "schema_version": "1.0.0",
  "repo": "string (repository name)",
  "commit_sha": "string (40-char SHA)",
  "branch": "string (git branch name)",
  "tag": "string (tag name, e.g., v1.0.0)",
  "tag_object_sha": "string (SHA of the tag object if annotated, else commit SHA)",
  "tag_type": "string (annotated_signed | annotated_unsigned | lightweight | absent)",
  "manifest_hash": "string (SHA256 hex hash of this JSON excluding signature/mutable fields)",
  "artifact_hashes": {
    "filename": "sha256_hash_string"
  },
  "dependency_lock_hashes": {
    "lockfile_name": "sha256_hash_string"
  },
  "test_evidence": {
    "evidence_file": "sha256_hash_string"
  },
  "ci_pipeline_id": "string or null",
  "signer_key_id": "string or null (GPG key ID)",
  "signature_algorithm": "string or null (e.g. gpg)",
  "signature": "string or null (ASCII armored PGP signature)",
  "previous_release": "string or null",
  "generated_at": "string (ISO 8601 UTC timestamp)",
  "verification_status": "string (signed | unsigned)"
}
```

## 2. Signing Requirements

1. **Manifest Signing**: The `manifest_hash` is computed by serializing the JSON manifest with `manifest_hash`, `signature`, `signer_key_id`, `signature_algorithm`, and `verification_status` fields set to `null` or `"unsigned"`. The GPG key is used to sign the resulting hash.
2. **Key Material**: Signatures must use a trusted GPG key ID.
3. **Passphrase/KMS**: Local builds require the signer's GPG key passphrase. In automated CI pipelines where GPG private keys are unavailable, manifests are generated as `verification_status: "unsigned"` (draft) and will be validated as unsigned.

## 3. Tag Requirements

1. **Tag Type**: All new releases must use annotated tags. Lightweight tags are prohibited for production release candidates.
2. **Tag Signing**: New tags must be cryptographically signed using GPG (`git tag -s`).
3. **Enforcement**: Any release tag that is not `annotated_signed` will fail release verification.

## 4. Verification Command

Verification is performed using the `verify_release_provenance.py` script:

```bash
python3 scripts/release/verify_release_provenance.py --manifest release_manifest.json
```

Verification fails if:
- Recomputed `manifest_hash` does not match the one in the manifest.
- The tag type is not `annotated_signed` for a release candidate.
- The manifest's GPG signature is invalid or missing when signed verification is enabled.
- Artifact hashes or dependency lockfile hashes on disk do not match the manifest entries.
- Any release-bound governance attestation contains a `signature: null` field.

## 5. CI Expectations

The CI pipeline must:
1. Run the verifier script on all merge requests and release pipeline triggers.
2. Enforce that release pipelines only proceed if the current tag type is `annotated_signed`.
3. Reject unsigned or unverified manifests for release builds, failing closed.

## 6. Historical Unsigned Tags

1. **Classification**: Existing legacy tags created before this specification was adopted are grandfathered in as **accepted legacy risk** and listed in `RELEASE_PROVENANCE_STATUS.md`.
2. **Replacement**: Legacy tags will not be rewritten to protect repository history, but all subsequent release candidates must strictly conform to this specification.

## 7. Fallback Behavior

If GPG keys or passphrases are missing:
- Manifest generation falls back to an unsigned draft manifest (`signature: null`, `verification_status: "unsigned"`).
- Verification fails if signed verification is required, or passes with warnings stating that `signed release provenance` is **not proven**.
- No repo may claim signed release provenance without a verifiable signature.

## 8. CI Signing Dry-Run (Non-Tag Positive Proof) — SDD-GATE-SIGNING-001

**Signing architecture (Option A — GPG in CI).** Manifest signing is GPG. The
generator (`scripts/release/generate_release_manifest.py`) produces a detached,
ASCII-armored signature over `manifest_hash` and embeds it in the manifest
(`signature`, `signer_key_id`, `signature_algorithm: "gpg"`). The generator
signs **non-interactively** with passphrase-protected keys via
`--pinentry-mode loopback` and a passphrase read from a dedicated file
descriptor — never from argv. Container-image signing uses cosign separately and
is **not** part of this JSON-manifest contract; do not switch manifest signing to
cosign without rewriting `verify_release_provenance.py`.

**Required CI variables** (protected group variables, exposed only on protected
branches/tags):
- `GPG_PRIVATE_KEY` — ASCII-armored private key (imported into an ephemeral
  `GNUPGHOME`). Note: this variable is **not masked**, so it must never be echoed.
- `GPG_PASSPHRASE` (or `RELEASE_SIGNING_PASSPHRASE`) — signing passphrase.
- `GPG_KEY_ID` (or `RELEASE_SIGNING_KEY_ID`) — expected signer key id; the
  verifier rejects a manifest whose `signer_key_id` does not match it.

**Secret-handling rules.**
- Import the key under `set +x`; never `echo`/`cat`/print key or passphrase.
- Never pass the passphrase via argv (use `--passphrase-fd`).
- Use an ephemeral `GNUPGHOME="$(mktemp -d)"`, removed via `trap ... EXIT`.
- Never commit key material; artifacts contain only the verification verdict JSON.

**Non-tag dry-run behavior.** The `release_manifest_signing_dry_run` CI job runs
as a **manual job on the protected default branch (`main`)**, where the protected
GPG variables are exposed (default-branch evidence is the proof of record). It
generates a signed manifest with `--require-signing`
(an unsigned result fails the job closed), then runs the verifier and asserts
`manifest_signature_verified == true`, `signature_algorithm == "gpg"`, and no
errors. It does **not** create a tag, does **not** deploy, and does **not**
require a signed tag.

**Release-tag requirement for full closure.** Full `--require-signed` verification
requires **both** a signed manifest **and** an `annotated_signed` tag. The dry-run
deliberately does not require the tag.

**Proven vs not proven.**
- *Proven by the dry-run:* signed manifest generation and signature verification
  with the real protected key, non-interactively, in CI.
- *Not proven by the dry-run:* signed-release closure. **Manifest signing dry-run
  proves signed manifest generation and verification. It does not prove signed
  release closure unless the release tag is also annotated and signed.** No
  production-readiness claim is implied.

## Signed-tag dry-run (SDD-GOV-SIGNTAG-001)

The full `--require-signed` path (signed manifest **and** cryptographically
verified annotated signed tag) is proven without creating or pushing a
production release tag. See [SIGNED_TAG_DRY_RUN.md](./SIGNED_TAG_DRY_RUN.md).
