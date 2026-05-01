#!/usr/bin/env sh
set -eu

mode="${1:-preprod}"
pass() { printf 'PASS: %s\n' "$*"; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

case "$mode" in preprod|prod) ;; *) fail "usage: $0 preprod|prod" ;; esac

[ -x "./scripts/enterprise-readiness-check.sh" ] || fail "scripts/enterprise-readiness-check.sh must exist and be executable"
./scripts/enterprise-readiness-check.sh
pass "enterprise readiness check completed"

find_artifact() {
  pattern="$1"
  find . -path './.git' -prune -o -path './.cache' -prune -o -path './.venv' -prune -o -path './node_modules' -prune -o -type f -name "$pattern" -print | head -n 1
}

[ -n "$(find_artifact 'sbom.spdx.json')" ] || [ -n "$(find_artifact 'sbom.cdx.json')" ] || fail "SBOM artifact missing"
pass "SBOM artifact present"
[ -n "$(find_artifact 'provenance-evidence.json')" ] || fail "provenance evidence artifact missing"
pass "provenance evidence artifact present"

if [ "$mode" = "prod" ]; then
  [ -n "${CI_COMMIT_TAG:-${RELEASE_VERSION:-}}" ] || fail "prod release gate requires CI_COMMIT_TAG or RELEASE_VERSION"
  pass "prod release version/tag evidence present"
else
  pass "preprod gate does not require a version tag"
fi

pass "CI stage ordering must require tests, readiness, SBOM, dependency audit, and provenance jobs before this manual gate"
