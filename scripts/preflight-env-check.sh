#!/usr/bin/env sh
set -eu

env_name="${APP_ENV:-${SYNDICATECLAW_ENV:-dev}}"
failures=0
warnings=0
fail() { failures=$((failures + 1)); printf 'FAIL: %s\n' "$*"; }
warn() { warnings=$((warnings + 1)); printf 'WARN: %s\n' "$*"; }
pass() { printf 'PASS: %s\n' "$*"; }

[ -f pyproject.toml ] && pass "pyproject.toml present" || fail "pyproject.toml missing"
[ -d "${TMPDIR:-/tmp}" ] && [ -w "${TMPDIR:-/tmp}" ] && pass "temp directory writable" || fail "temp directory is not writable"

case "$env_name" in
  prod|production)
    [ -n "${SYNDICATECLAW_DATABASE_URL:-}" ] || fail "SYNDICATECLAW_DATABASE_URL required in production"
    [ -n "${SYNDICATECLAW_SECRET_KEY:-}" ] || fail "SYNDICATECLAW_SECRET_KEY required in production"
    [ -n "${SYNDICATECLAW_OIDC_JWKS_URL:-}" ] || warn "OIDC JWKS URL not set; confirm non-OIDC auth mode is approved"
    [ "${SYNDICATECLAW_RBAC_ENFORCEMENT_ENABLED:-true}" = "true" ] || fail "RBAC enforcement must not be disabled in production"
    case "${SYNDICATECLAW_BASE_URL:-}" in
      *localhost*|*127.0.0.1*) warn "production base URL points at localhost" ;;
    esac
    ;;
  *) pass "non-production environment selected ($env_name)" ;;
esac

if command -v getent >/dev/null 2>&1; then
  getent hosts "${SYNDICATECLAW_DNS_CHECK_HOST:-localhost}" >/dev/null 2>&1 && pass "DNS lookup works" || warn "DNS lookup failed for ${SYNDICATECLAW_DNS_CHECK_HOST:-localhost}"
fi

[ "$failures" -eq 0 ] || exit 1
printf 'PASS: preflight completed with %s warning(s)\n' "$warnings"
