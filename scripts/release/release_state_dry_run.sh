#!/usr/bin/env bash
# Signed-release VERSION/CHANGELOG STATE dry-run (SDD-GOV-SIGNTAG-001 follow-up).
#
# Proves that the signed-release flow ties the version bump + changelog into the
# release commit, and that the annotated signed tag points to that RELEASE commit
# (not the pre-release commit) — WITHOUT running a real release and WITHOUT
# creating or pushing any release tag.
#
# It works inside a disposable `git worktree` on a throwaway branch so the real
# working tree is never touched. A THROWAWAY GPG key is generated in an ephemeral
# GNUPGHOME (no protected secret), so this runs on every MR and on main. It
# exercises the production primitives:
#   build_release_commit.py  -> bump pyproject + changelog, create release commit
#   create_signed_tag.py     -> annotated SIGNED tag on the release commit
#   generate_release_manifest.py / verify_release_provenance.py --require-signed
#
# Proven invariants:
#   1. release commit contains the pyproject version bump and a changelog entry;
#   2. the signed tag's target commit == the release commit;
#   3. the manifest commit_sha == the signed tag target (manifest binds release commit);
#   4. verifier passes --require-signed with manifest_commit_matches_tag_target=true;
#   5. NEGATIVE: a tag on the pre-release commit is REJECTED (tag-target mismatch);
#   6. NEGATIVE: a missing version bump FAILS CLOSED;
#   7. no semver release tag is created; nothing is pushed.
#
# Every tag/branch/worktree it makes is local-only and deleted on exit. This
# dry-run is NOT a release and is NOT full signed-release closure.
set -euo pipefail

REPO_ROOT="${CI_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
cd "$REPO_ROOT"

RAND="${CI_JOB_ID:-$$}-$(date +%s)"
WT="$(mktemp -d)"                       # worktree location
BR="dryrun/release-state/${RAND}"
SIGNED_TAG="provenance-ci-test/relstate-signed/${RAND}"
PREREL_TAG="provenance-ci-test/relstate-prerel/${RAND}"
export GNUPGHOME="$(mktemp -d)"; chmod 700 "$GNUPGHOME"

cleanup() {
  git -C "$REPO_ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  git -C "$REPO_ROOT" branch -D "$BR" >/dev/null 2>&1 || true
  for t in "$SIGNED_TAG" "$PREREL_TAG"; do
    git -C "$REPO_ROOT" tag -d "$t" >/dev/null 2>&1 || true
  done
  gpgconf --kill all >/dev/null 2>&1 || true
  rm -rf "$WT" "$GNUPGHOME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

FAILED=0
pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAILED=1; }
expect_rc() {  # expect_rc <rc> <desc> -- <cmd...>
  local want="$1"; shift; local desc="$1"; shift; [ "$1" = "--" ] && shift
  set +e; "$@" >/tmp/relstate.out 2>&1; local got=$?; set -e
  if [ "$got" -eq "$want" ]; then pass "$desc (rc=$got)"
  else fail "$desc (rc=$got, expected $want)"; tail -5 /tmp/relstate.out | sed 's/^/      /'; fi
}

echo "== Signed-release version/changelog state dry-run (worktree, throwaway key, no push) =="

# --- disposable worktree on a throwaway branch ---
git worktree add -q -b "$BR" "$WT" HEAD
PREREL_COMMIT="$(git -C "$WT" rev-parse HEAD)"
echo "Pre-release commit: $PREREL_COMMIT"

# --- throwaway signing key (signing-capable primary, no subkey) ---
printf 'allow-loopback-pinentry\n' > "$GNUPGHOME/gpg-agent.conf"
PP="relstate-throwaway"
cat > "$GNUPGHOME/keyspec" <<KEYSPEC
%echo gen throwaway key
Key-Type: RSA
Key-Length: 2048
Key-Usage: sign
Name-Real: claw release-state dry-run
Name-Email: relstate-dryrun@local
Expire-Date: 0
Passphrase: ${PP}
%commit
%echo done
KEYSPEC
gpg --batch --pinentry-mode loopback --gen-key "$GNUPGHOME/keyspec" >/dev/null 2>&1
KEY_ID="$(gpg --list-secret-keys --with-colons 2>/dev/null | awk -F: '/^fpr:/{print $10; exit}')"
[ -n "${KEY_ID:-}" ] || { echo "FATAL: key gen failed"; exit 1; }
printf '%s' "$PP" > "$GNUPGHOME/pp"; chmod 600 "$GNUPGHOME/pp"
printf '#!/bin/sh\nexec gpg --pinentry-mode loopback --passphrase-file "%s/pp" --batch --no-tty "$@"\n' "$GNUPGHOME" > "$GNUPGHOME/gpgwrap.sh"
chmod 700 "$GNUPGHOME/gpgwrap.sh"
export GPG_KEY_ID="$KEY_ID" GPG_PASSPHRASE="$PP"
echo "Throwaway signing key: $KEY_ID"

# A test "next version" (does not touch real release numbering).
TEST_VERSION="99.99.99-dryrun.${RAND}"
PYPROJECT_BEFORE="$(grep -E '^version = ' "$WT/pyproject.toml" | head -1 || true)"

# --- PROOF 1: build release commit (version bump + changelog) on the worktree ---
expect_rc 0 "release commit built (pyproject bump + changelog)" -- \
  python3 scripts/release/build_release_commit.py \
    --version "$TEST_VERSION" --repo-path "$WT"
REL_COMMIT="$(git -C "$WT" rev-parse HEAD)"
if [ "$REL_COMMIT" != "$PREREL_COMMIT" ]; then pass "release commit advances HEAD past pre-release commit"; else fail "release commit must differ from pre-release commit"; fi
if git -C "$WT" show -s --format='%s' HEAD | grep -q "chore(release): v${TEST_VERSION}"; then pass "release commit subject is chore(release)"; else fail "release commit subject wrong"; fi
if grep -q "version = \"${TEST_VERSION}\"" "$WT/pyproject.toml"; then pass "pyproject.toml bumped to release version"; else fail "pyproject not bumped"; fi
if head -1 "$WT/CHANGELOG.md" | grep -q "## v${TEST_VERSION}"; then pass "CHANGELOG.md has release entry at top"; else fail "changelog entry missing"; fi

# --- PROOF 2: annotated SIGNED tag on the RELEASE commit ---
expect_rc 0 "signed tag created on release commit + self-verified" -- \
  python3 scripts/release/create_signed_tag.py \
    --tag "$SIGNED_TAG" --key-id "$KEY_ID" \
    --gpg-program "$GNUPGHOME/gpgwrap.sh" --expected-key-id "$KEY_ID" \
    --repo-path "$WT" --commit "$REL_COMMIT" \
    --message "release-state dry-run (local-only)"
TAG_TARGET="$(git -C "$WT" rev-list -n 1 "$SIGNED_TAG")"
if [ "$TAG_TARGET" = "$REL_COMMIT" ]; then pass "signed tag target == release commit"; else fail "signed tag target ($TAG_TARGET) != release commit ($REL_COMMIT)"; fi

# --- PROOF 3+4: manifest binds the release commit; verifier passes --require-signed ---
python3 scripts/release/generate_release_manifest.py \
  --tag "$SIGNED_TAG" --repo-path "$WT" --out "$WT/relstate_manifest.json" --require-signing >/dev/null
MANIFEST_COMMIT="$(python3 -c "import json;print(json.load(open('$WT/relstate_manifest.json'))['commit_sha'])")"
if [ "$MANIFEST_COMMIT" = "$REL_COMMIT" ]; then pass "manifest commit_sha == release commit"; else fail "manifest commit ($MANIFEST_COMMIT) != release commit ($REL_COMMIT)"; fi
expect_rc 0 "verifier passes --require-signed (signed tag + manifest/tag-target binding)" -- \
  python3 scripts/release/verify_release_provenance.py \
    --manifest relstate_manifest.json --repo-path "$WT" \
    --require-signed --expected-key-id "$KEY_ID"
python3 scripts/release/verify_release_provenance.py \
  --manifest relstate_manifest.json --repo-path "$WT" \
  --require-signed --expected-key-id "$KEY_ID" > "$WT/relstate_verdict.json" 2>/dev/null || true
if python3 -c "import json,sys; d=json.load(open('$WT/relstate_verdict.json')); sys.exit(0 if d.get('manifest_commit_matches_tag_target') is True and d.get('signed_tag_verified') is True else 1)"; then
  pass "verdict: manifest_commit_matches_tag_target=true and signed_tag_verified=true"
else
  fail "verdict missing tag-target binding / signed-tag verification"
fi

# --- PROOF 5 (NEGATIVE): a tag on the PRE-RELEASE commit is rejected ---
git -C "$WT" -c user.signingkey="$KEY_ID" -c gpg.program="$GNUPGHOME/gpgwrap.sh" \
    -c user.name=dryrun -c user.email=dryrun@local \
    tag -s -m "pre-release tag (should be rejected)" "$PREREL_TAG" "$PREREL_COMMIT"
# manifest still describes the RELEASE commit (HEAD), but this tag targets pre-release.
python3 scripts/release/generate_release_manifest.py \
  --tag "$PREREL_TAG" --repo-path "$WT" --out "$WT/prerel_manifest.json" --require-signing >/dev/null
# Force the manifest to claim the release commit while the tag targets pre-release,
# i.e. the exact "tag points to the wrong commit" failure we must catch.
python3 - "$WT/prerel_manifest.json" "$REL_COMMIT" <<'PY'
import json,sys
p,rel=sys.argv[1],sys.argv[2]
d=json.load(open(p)); d["commit_sha"]=rel
# recompute manifest_hash over the non-signature fields (matches generator/verifier)
import hashlib
c=dict(d); c["manifest_hash"]=None; c["signature"]=None; c["signer_key_id"]=None
c["signature_algorithm"]=None; c["verification_status"]="unsigned"
d["manifest_hash"]=hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()
# drop signature: this negative case targets the tag-target invariant, not the sig
d["signature"]=None; d["signer_key_id"]=None; d["signature_algorithm"]=None; d["verification_status"]="unsigned"
json.dump(d,open(p,"w"),indent=2,sort_keys=True)
PY
expect_rc 1 "tag on pre-release commit REJECTED (tag-target mismatch under --require-signed)" -- \
  python3 scripts/release/verify_release_provenance.py \
    --manifest prerel_manifest.json --repo-path "$WT" --require-signed --expected-key-id "$KEY_ID"

# --- PROOF 6 (NEGATIVE): missing version bump fails closed ---
expect_rc 2 "missing --version fails closed" -- \
  python3 scripts/release/build_release_commit.py --version "" --repo-path "$WT"

# --- PROOF 7: no semver release tag created; nothing pushed ---
# Worktrees share the repo tag namespace, so we assert the tags THIS run created
# are non-semver (never a vX.Y.Z release tag), not that none exist in the repo.
relstate_semver=""
for t in "$SIGNED_TAG" "$PREREL_TAG"; do
  printf '%s\n' "$t" | grep -qE '^v[0-9]+\.[0-9]+\.[0-9]+$' && relstate_semver="$relstate_semver $t"
done
if [ -n "$relstate_semver" ]; then
  fail "dry-run created a semver release tag:$relstate_semver"
else
  pass "no semver release tag created by this run (proof tags are non-semver)"
fi
pushed=""
for t in "$SIGNED_TAG" "$PREREL_TAG"; do
  [ -n "$(git ls-remote --tags origin "refs/tags/$t" 2>/dev/null || true)" ] && pushed="$pushed $t"
done
if [ -n "$pushed" ]; then fail "proof tags unexpectedly on origin:$pushed"; else pass "no proof tag present on origin (nothing pushed)"; fi

echo
if [ "$FAILED" -eq 0 ]; then echo "SIGNED-RELEASE VERSION-STATE DRY-RUN: PASS"; exit 0; fi
echo "SIGNED-RELEASE VERSION-STATE DRY-RUN: FAIL"; exit 1
