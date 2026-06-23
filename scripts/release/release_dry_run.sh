#!/usr/bin/env bash
# Signed-release flow dry-run validation (SDD-GOV-SIGNTAG-001 follow-up).
#
# Proves the syndicateclaw signed-release path WITHOUT any protected secret and
# WITHOUT creating or pushing a real release tag. It generates a THROWAWAY GPG
# key in an ephemeral GNUPGHOME and exercises the production primitives
# (scripts/release/create_signed_tag.py, generate_release_manifest.py,
# verify_release_provenance.py) to prove:
#
#   1. the configured path creates an annotated, cryptographically verifiable
#      SIGNED tag;
#   2. a signed manifest bound to that tag verifies under --require-signed;
#   3. a LIGHTWEIGHT tag is REJECTED under --require-signed;
#   4. an UNSIGNED annotated tag is REJECTED under --require-signed;
#   5. missing signing material FAILS CLOSED (--require-signing);
#   6. the release-tag guard refuses to mint a semver vX.Y.Z tag without
#      explicit authorization;
#   7. no proof tag is pushed to origin.
#
# Because it mints its own throwaway key it needs no protected variables and can
# run on every merge request. It is NOT a release: every tag it creates is
# non-semver, local-only, and deleted on exit. This dry-run proof is NOT full
# signed-release closure (see docs/release/SIGNED_RELEASE_FLOW.md).
set -euo pipefail

REPO_ROOT="${CI_PROJECT_DIR:-$(git rev-parse --show-toplevel)}"
cd "$REPO_ROOT"

RAND="${CI_JOB_ID:-$$}-$(date +%s)"
SIGNED_TAG="provenance-ci-test/signed-flow-dryrun/${RAND}"
LW_TAG="provenance-ci-test/lightweight-dryrun/${RAND}"
UA_TAG="provenance-ci-test/unsigned-annotated-dryrun/${RAND}"
GUARD_TAG="v9.9.9"   # must be refused by the guard; never created

export GNUPGHOME="$(mktemp -d)"
chmod 700 "$GNUPGHOME"
EMPTY_GNUPGHOME="$(mktemp -d)"
chmod 700 "$EMPTY_GNUPGHOME"

cleanup() {
  for t in "$SIGNED_TAG" "$LW_TAG" "$UA_TAG" "$GUARD_TAG"; do
    git tag -d "$t" >/dev/null 2>&1 || true
  done
  gpgconf --kill all >/dev/null 2>&1 || true
  rm -rf "$GNUPGHOME" "$EMPTY_GNUPGHOME" >/dev/null 2>&1 || true
  rm -f dryrun_signed.json dryrun_lw.json dryrun_ua.json >/dev/null 2>&1 || true
}
trap cleanup EXIT

FAILED=0
pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAILED=1; }

# expect_rc <expected_rc> <description> -- <command...>
expect_rc() {
  local want="$1"; shift
  local desc="$1"; shift
  [ "$1" = "--" ] && shift
  set +e
  "$@" >/tmp/dryrun.out 2>&1
  local got=$?
  set -e
  if [ "$got" -eq "$want" ]; then
    pass "$desc (rc=$got)"
  else
    fail "$desc (rc=$got, expected $want)"
    tail -5 /tmp/dryrun.out | sed 's/^/      /'
  fi
}

echo "== Signed-release flow dry-run (throwaway key, no secrets, no push) =="

# --- throwaway key + loopback signing infra (mirrors production) ---
printf 'allow-loopback-pinentry\n' > "$GNUPGHOME/gpg-agent.conf"
PP="dryrun-throwaway-passphrase"
# A signing-capable PRIMARY key with NO subkey: the primary itself signs, so the
# git verify-tag VALIDSIG fingerprint equals the key id we pass as expected.
cat > "$GNUPGHOME/keyspec" <<KEYSPEC
%echo generating throwaway dry-run key
Key-Type: RSA
Key-Length: 2048
Key-Usage: sign
Name-Real: syndicateclaw release dry-run
Name-Email: release-dryrun@local
Expire-Date: 0
Passphrase: ${PP}
%commit
%echo done
KEYSPEC
gpg --batch --pinentry-mode loopback --gen-key "$GNUPGHOME/keyspec" >/dev/null 2>&1
KEY_ID="$(gpg --list-secret-keys --with-colons 2>/dev/null | awk -F: '/^fpr:/{print $10; exit}')"
if [ -z "${KEY_ID:-}" ]; then echo "FATAL: throwaway key generation failed"; exit 1; fi
echo "Throwaway signing key: ${KEY_ID}"

printf '%s' "$PP" > "$GNUPGHOME/pp"
chmod 600 "$GNUPGHOME/pp"
printf '#!/bin/sh\nexec gpg --pinentry-mode loopback --passphrase-file "%s/pp" --batch --no-tty "$@"\n' "$GNUPGHOME" > "$GNUPGHOME/gpgwrap.sh"
chmod 700 "$GNUPGHOME/gpgwrap.sh"

# generator reads these for signing (passphrase travels on an fd, never argv)
export GPG_KEY_ID="$KEY_ID"
export GPG_PASSPHRASE="$PP"

# --- PROOF 1: the path creates an annotated SIGNED tag and self-verifies ---
expect_rc 0 "signed annotated tag created + cryptographically verified" -- \
  python3 scripts/release/create_signed_tag.py \
    --tag "$SIGNED_TAG" --key-id "$KEY_ID" \
    --gpg-program "$GNUPGHOME/gpgwrap.sh" \
    --expected-key-id "$KEY_ID" \
    --message "signed-release flow dry-run (local-only, never pushed)"
expect_rc 0 "git verify-tag confirms the signed tag" -- \
  git verify-tag "$SIGNED_TAG"

# --- PROOF 2: signed manifest bound to the tag passes --require-signed ---
python3 scripts/release/generate_release_manifest.py \
  --tag "$SIGNED_TAG" --out dryrun_signed.json --require-signing >/dev/null
expect_rc 0 "signed manifest + signed tag verify under --require-signed" -- \
  python3 scripts/release/verify_release_provenance.py \
    --manifest dryrun_signed.json --repo-path . \
    --require-signed --expected-key-id "$KEY_ID"

# --- PROOF 3: LIGHTWEIGHT tag is rejected under --require-signed ---
# Force tag.gpgSign=false so this is genuinely lightweight regardless of any
# ambient git config that defaults tags to signed.
git -c tag.gpgSign=false tag "$LW_TAG"
python3 scripts/release/generate_release_manifest.py \
  --tag "$LW_TAG" --out dryrun_lw.json >/dev/null
expect_rc 1 "lightweight tag REJECTED by --require-signed" -- \
  python3 scripts/release/verify_release_provenance.py \
    --manifest dryrun_lw.json --repo-path . --require-signed

# --- PROOF 4: UNSIGNED annotated tag is rejected under --require-signed ---
git -c tag.gpgSign=false -c user.email="dryrun@local" -c user.name="dryrun" \
  tag -a -m "unsigned annotated dry-run" "$UA_TAG"
python3 scripts/release/generate_release_manifest.py \
  --tag "$UA_TAG" --out dryrun_ua.json >/dev/null
expect_rc 1 "unsigned annotated tag REJECTED by --require-signed" -- \
  python3 scripts/release/verify_release_provenance.py \
    --manifest dryrun_ua.json --repo-path . --require-signed

# --- PROOF 5: missing signing material FAILS CLOSED ---
expect_rc 1 "missing signing key fails closed (--require-signing)" -- \
  env -u GPG_KEY_ID -u GPG_PASSPHRASE -u RELEASE_SIGNING_KEY_ID \
      -u RELEASE_SIGNING_PASSPHRASE GNUPGHOME="$EMPTY_GNUPGHOME" \
  python3 scripts/release/generate_release_manifest.py \
    --out /tmp/dryrun_nokey.json --require-signing

# --- PROOF 6: release-tag guard refuses a semver tag without authorization ---
expect_rc 2 "release-tag guard refuses vX.Y.Z without --allow-release-tag" -- \
  python3 scripts/release/create_signed_tag.py \
    --tag "$GUARD_TAG" --key-id "$KEY_ID" \
    --gpg-program "$GNUPGHOME/gpgwrap.sh" --message "should be refused"
if git rev-parse -q --verify "refs/tags/$GUARD_TAG" >/dev/null 2>&1; then
  fail "guard tag $GUARD_TAG must NOT exist"
else
  pass "guard tag $GUARD_TAG was not created"
fi

# --- PROOF 7: no proof tag was pushed to origin ---
pushed=""
for t in "$SIGNED_TAG" "$LW_TAG" "$UA_TAG"; do
  if [ -n "$(git ls-remote --tags origin "refs/tags/$t" 2>/dev/null || true)" ]; then
    pushed="$pushed $t"
  fi
done
if [ -n "$pushed" ]; then
  fail "proof tags unexpectedly present on origin:$pushed"
else
  pass "no proof tag present on origin (nothing pushed)"
fi

echo
if [ "$FAILED" -eq 0 ]; then
  echo "SIGNED-RELEASE DRY-RUN: PASS"
  exit 0
fi
echo "SIGNED-RELEASE DRY-RUN: FAIL"
exit 1
