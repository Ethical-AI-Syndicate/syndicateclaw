# Signed Release Flow

**Spec ID:** SDD-GOV-SIGNTAG-001 (follow-up implementation)
**Branch of record:** `sdd/claw-signed-release-flow`
**Status of this artifact:** design + operator documentation
**Applies to:** `.gitlab-ci.yml` (`release`, `release_signed_flow_dry_run`),
`scripts/release/create_signed_tag.py`, `scripts/release/release_dry_run.sh`,
`scripts/release/generate_release_manifest.py`,
`scripts/release/verify_release_provenance.py`, `.releaserc.json`.

## Intent

Make every `syndicateclaw` release tag an **annotated, GPG-signed** tag created
only under an explicit, operator-initiated release context — replacing the prior
behavior where `semantic-release` emitted **lightweight, unsigned** tags (the
root cause of the unintended `v2.2.10`).

A release is **signed or it does not happen**: the `release` job fails closed if
signing key material is absent.

## Why not let semantic-release sign tags directly?

`semantic-release` core creates **lightweight** tags and has no native option to
produce annotated or signed tags, and there is no official plugin that replaces
its tag-creation step. So signing it "directly" (Option A) is not available.

This repo therefore uses **Option B**:

1. `semantic-release --dry-run` computes the next version from conventional
   commits (no tag, no commit, no push — version determination only);
2. `scripts/release/create_signed_tag.py` creates the annotated **signed** tag
   `vX.Y.Z`;
3. `generate_release_manifest.py` + `verify_release_provenance.py --require-signed`
   prove the manifest signature **and** the signed tag;
4. only then is the tag pushed.

A dedicated release script that abandons `semantic-release` entirely (Option C)
was rejected as heavier with no added safety: `semantic-release` already does
conventional-commit version + notes computation correctly.

## The flow (production `release` job — explicit context only)

```
web pipeline on main + RELEASE=true
  └─ fail closed if GPG_PRIVATE_KEY / GPG_KEY_ID absent
  └─ import key into an ephemeral GNUPGHOME (loopback pinentry, passphrase via file)
  └─ VERSION = semantic-release --dry-run        # version only; no side effects
  └─ build_release_commit.py --version VERSION   # bump pyproject + changelog, COMMIT
  └─ REL_COMMIT = git rev-parse HEAD             # the release commit
  └─ create_signed_tag.py --tag vVERSION --commit REL_COMMIT --allow-release-tag
  └─ git verify-tag vVERSION
  └─ generate_release_manifest.py --tag vVERSION --require-signing
  └─ verify_release_provenance.py --require-signed --expected-key-id GPG_KEY_ID
        # also asserts manifest commit_sha == signed tag target (REL_COMMIT)
  └─ git push origin HEAD:main                   # release commit, then
  └─ git push origin refs/tags/vVERSION          # the tag — the ONLY pushes, only here
```

### Release commit / tag ordering (the invariant this remediation adds)

1. The **release commit** is built first: `build_release_commit.py` bumps
   `pyproject.toml` to the release version and prepends a `CHANGELOG.md` entry,
   then creates an (unsigned) `chore(release): vX.Y.Z [skip ci]` commit. It fails
   closed if it cannot bump the version or would produce no change.
2. The annotated **signed tag** is created **on the release commit**
   (`--commit REL_COMMIT`), so the tag targets release state — not the
   pre-release commit.
3. The provenance manifest is generated at that commit, and
   `verify_release_provenance.py --require-signed` now additionally asserts
   `manifest commit_sha == signed tag target commit`. A tag pointing at any other
   commit is an error.
4. Only then are the release commit and tag pushed.

The release **commit** is intentionally unsigned; the signed **tag** is the
provenance anchor (same model semantic-release uses). `create_signed_tag.py`
never pushes and never takes a passphrase on argv; the passphrase is read from a
file by git's configured `gpg.program` wrapper. It **refuses** to create a semver
`vX.Y.Z` tag unless `--allow-release-tag` is passed, so only the authorized
release context can mint a real release tag.

## Release operator steps

1. Ensure `main` is green and at the commit you intend to release.
2. GitLab → **CI/CD → Pipelines → Run pipeline**, ref `main`.
3. Add variable `RELEASE` = `true`.
4. Run. The `release` job computes the version, builds the release commit
   (version bump + changelog), creates and verifies the signed tag **on that
   commit**, and pushes the commit + tag. If no release is due (no `fix:`/`feat:`
   since the last release) the job exits cleanly without creating a tag.

There is no automatic release on an ordinary `main` push — see
[`RELEASE_FLOW_GATING.md`](./RELEASE_FLOW_GATING.md).

### What the operator must verify before authorizing a real release

- `main` is green and is the exact commit to release.
- The protected `GPG_PRIVATE_KEY` / `GPG_KEY_ID` / `GPG_PASSPHRASE` variables are
  present on `main` and the key id is the intended release signer.
- After the run: the new `vX.Y.Z` tag is **annotated + signed**, `git verify-tag`
  passes, and `verify_release_provenance.py --require-signed --expected-key-id`
  returns `status: pass` with `signed_tag_verified: true`,
  `manifest_signature_verified: true`, and
  `manifest_commit_matches_tag_target: true`.
- The tag points to the `chore(release): vX.Y.Z` commit (release state), and that
  commit is on `main`.

## Required CI variables (protected, on `main`)

| Variable | Purpose | Notes |
|---|---|---|
| `GPG_PRIVATE_KEY` | Signing key import | Protected, masked. Raw armored / base64 / escaped all accepted. |
| `GPG_KEY_ID` | Signer identity asserted on tag + manifest | Long key id or fingerprint. |
| `GPG_PASSPHRASE` | Key passphrase | Read from a file by the gpg wrapper; never passed via argv. |

`RELEASE_SIGNING_KEY_ID` / `RELEASE_SIGNING_PASSPHRASE` are accepted as
release-tooling aliases by the generator/verifier.

## How signed tags are created and verified

- **Created** by `create_signed_tag.py` via `git tag -s` with the configured
  signing key, then immediately verified with the same `git verify-tag`
  GOODSIG+VALIDSIG check used by release provenance. If verification fails the
  just-created tag is deleted (no unverified tag is left behind).
- **Verified** by `verify_release_provenance.py`: under `--require-signed` it
  rejects a lightweight tag, rejects an unsigned annotated tag, requires the
  manifest signature to verify, and requires the tag signer to match
  `--expected-key-id`. This path is never weakened by this change.

## Dry-run proof (CI-enforced, no secrets)

`release_signed_flow_dry_run` runs `scripts/release/release_dry_run.sh` on every
MR and on `main`. It generates a **throwaway** GPG key in-job (so it needs no
protected variable) and proves, against the real production primitives, that:

1. the path creates an annotated signed tag that cryptographically verifies;
2. a signed manifest bound to that tag passes `--require-signed`;
3. a **lightweight** tag is rejected under `--require-signed`;
4. an **unsigned annotated** tag is rejected under `--require-signed`;
5. missing signing material **fails closed** (`--require-signing`);
6. the release-tag guard refuses a semver tag without authorization;
7. no proof tag is pushed.

Every tag it creates is non-semver, local-only, and deleted on exit.

### Version/changelog state proof

`release_state_dry_run` runs `scripts/release/release_state_dry_run.sh` on every
MR and on `main`, inside a disposable `git worktree` with a throwaway key. It
proves the release **state** invariants against the production primitives
(`build_release_commit.py`, `create_signed_tag.py`,
`generate_release_manifest.py`, `verify_release_provenance.py`):

1. the release commit carries the `pyproject.toml` version bump and a
   `CHANGELOG.md` entry;
2. the signed tag's target commit **is** the release commit;
3. the manifest `commit_sha` equals the signed tag target;
4. the verifier passes `--require-signed` with
   `manifest_commit_matches_tag_target: true` and `signed_tag_verified: true`;
5. **negative** — a tag on the **pre-release** commit is rejected
   (tag-target mismatch under `--require-signed`);
6. **negative** — a missing version bump fails closed;
7. no semver release tag is created; nothing is pushed.

Everything it creates (worktree, throwaway branch, non-semver tags) is local-only
and deleted on exit.

`release_signed_tag_dry_run` (manual, `main`-only) is the complementary proof
using the **real protected key**.

## Legacy lightweight tags (`v2.2.10` and earlier)

`v2.2.10` and earlier tags were created by the old lightweight/unsigned flow.
They are treated as **legacy** and left **untouched** — not deleted, rewritten,
or replaced. `verify_release_provenance.py` inventories them under
`unsigned_legacy_tags` for visibility. They do **not** satisfy `--require-signed`.

## Why the dry-run is NOT full signed-release closure

The dry-run proves the *path* and the release-state *invariants* work with a
*throwaway* key on a *non-semver, local-only* tag inside a disposable worktree.
It does **not** create a real, authorized, signed release tag. Full
signed-release closure is therefore **not proven** by this change.

The version bump + changelog + release-commit step is now **wired into the
production `release` job** (`build_release_commit.py` before tagging) and its
invariants are CI-proven in dry-run. Two scope limits remain **not proven**:

- The changelog body produced by `build_release_commit.py` is a **bounded summary
  of commit subjects**, not the full `@semantic-release/release-notes-generator`
  output. Exact semantic-release release-notes parity is **not claimed**.
- The production push of the release commit + signed tag has **not been executed**
  (no real release run), so end-to-end release-state behavior under the protected
  key is **not proven**.

## What event closes signed-release evidence

Signed-release evidence is closed only when, under the real `release` workflow
(web pipeline on `main` with `RELEASE=true` and the protected key), an
**authorized annotated signed release tag `vX.Y.Z`** is created on the
`chore(release): vX.Y.Z` commit, `git verify-tag` passes, and
`verify_release_provenance.py --require-signed --expected-key-id` returns
`status: pass` with `signed_tag_verified: true`,
`manifest_signature_verified: true`, and
`manifest_commit_matches_tag_target: true`. Until that specific event occurs and
its evidence is captured, signed-release closure remains **not proven**.

This change does not claim full signed-release closure and does not claim
production readiness.
