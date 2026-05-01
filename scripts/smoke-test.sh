#!/usr/bin/env sh
set -eu

./scripts/preflight-env-check.sh

health_url="${SYNDICATECLAW_HEALTH_URL:-}"
if [ -z "$health_url" ] && [ -n "${SYNDICATECLAW_BASE_URL:-}" ]; then
  health_url="${SYNDICATECLAW_BASE_URL%/}/healthz"
fi

if [ -n "$health_url" ]; then
  command -v curl >/dev/null 2>&1 || { printf 'FAIL: curl required for endpoint smoke test\n' >&2; exit 1; }
  curl -fsS --max-time "${SMOKE_TIMEOUT_SECONDS:-5}" "$health_url" >/dev/null
  printf 'PASS: health endpoint responded\n'
else
  PYTHONPATH=src python3 -m compileall -q src/syndicateclaw
  printf 'PASS: Python package compiles for smoke validation\n'
fi
