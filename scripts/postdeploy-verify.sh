#!/usr/bin/env sh
set -eu

./scripts/preflight-env-check.sh

base="${SYNDICATECLAW_BASE_URL:-}"
health="${SYNDICATECLAW_HEALTH_URL:-${base:+${base%/}/healthz}}"
ready="${SYNDICATECLAW_READY_URL:-${base:+${base%/}/readyz}}"

if [ -n "$health" ] || [ -n "$ready" ]; then
  command -v curl >/dev/null 2>&1 || { printf 'FAIL: curl required for postdeploy verification\n' >&2; exit 1; }
  [ -z "$health" ] || curl -fsS --max-time "${VERIFY_TIMEOUT_SECONDS:-10}" "$health" >/dev/null
  [ -z "$ready" ] || curl -fsS --max-time "${VERIFY_TIMEOUT_SECONDS:-10}" "$ready" >/dev/null
  printf 'PASS: health/readiness verification completed\n'
else
  printf 'WARN: no health/readiness URL configured\n'
fi

if command -v alembic >/dev/null 2>&1 && [ -f alembic.ini ] && [ -n "${SYNDICATECLAW_DATABASE_URL:-}" ]; then
  python3 -m alembic current || { printf 'FAIL: alembic current failed\n' >&2; exit 1; }
else
  printf 'WARN: migration status skipped; alembic or database URL unavailable\n'
fi
