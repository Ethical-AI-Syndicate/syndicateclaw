#!/usr/bin/env sh
set -eu

failures=0
fail() { failures=$((failures + 1)); printf 'FAIL: %s\n' "$*"; }
pass() { printf 'PASS: %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*"; }

[ -f ENTERPRISE_DEPLOYMENT_READINESS.md ] && [ -f SECURITY_EVIDENCE_PACK.md ] && [ -f TENANCY_MODEL.md ] && pass "evidence docs present" || fail "required evidence docs missing"
[ -x scripts/release-gate-check.sh ] && pass "release gate script present" || fail "release gate script missing"

if [ -f Dockerfile ]; then
  last_from="$(grep -n '^[[:space:]]*FROM[[:space:]]' Dockerfile | tail -1 | cut -d: -f1)"
  user_line="$(tail -n +"${last_from:-1}" Dockerfile | grep -E '^[[:space:]]*USER[[:space:]]+' | tail -1 || true)"
  case "$user_line" in *" root"|*" 0"|*" 0:0"|*" root:root"| "") fail "Dockerfile final stage does not set an obvious non-root USER" ;; *) pass "Dockerfile final stage uses non-root USER" ;; esac
fi

hits="$(mktemp)"
find deploy .gitlab-ci.yml Dockerfile Dockerfile.* docker-compose*.yml -type f 2>/dev/null \
  | grep -Ev '(^|/)(examples|sample|samples)(/|$)' \
  | xargs grep -En 'CHANGEME|CHANGE_ME|REPLACE_ME|dev-secret|admin-secret-change-in-prod|debug[[:space:]]*:[[:space:]]*true|DEBUG=true|CORS_ALLOWED_ORIGINS=.?\*' > "$hits" 2>/dev/null || true
if [ -s "$hits" ]; then
  fail "placeholder secret/debug/wildcard defaults found"
  sed -n '1,20p' "$hits" | sed 's/^/  /'
else
  pass "no obvious placeholder secrets/debug/wildcard defaults in active files"
fi
rm -f "$hits"

if find deploy -type f \( -name '*.yaml' -o -name '*.yml' \) 2>/dev/null | grep -v '/examples/' | xargs grep -En 'localhost|127\\.0\\.0\\.1' >/dev/null 2>&1; then
  warn "localhost references exist in active config; verify they are not production defaults"
else
  pass "no active localhost defaults found"
fi

if PYTHONPATH="${PYTHONPATH:-src}" python3 - <<'PY'
from syndicateclaw.config import Settings
fields = Settings.model_fields
required = {"oidc_jwks_url", "oidc_issuer", "jwt_audience"}
missing = required.difference(fields)
raise SystemExit(1 if missing else 0)
PY
then
  pass "auth issuer/audience config fields exist"
else
  fail "auth issuer/audience config fields missing"
fi

[ "$failures" -eq 0 ] || exit 1
pass "security review check completed"
