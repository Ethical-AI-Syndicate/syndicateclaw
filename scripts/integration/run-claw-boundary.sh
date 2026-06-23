#!/usr/bin/env bash
# Claw runtime authority boundary integration proof (SDD-CLAW-RUNTIME-BOUNDARY-001).
#
# Drives the REAL Claw runtime boundary (src/syndicateclaw/runtime_boundary) over a
# test ControlPlane re-validation harness (InMemoryControlPlaneValidator, which
# implements the same allow/deny/expired/revoked/consumed/unavailable contract a
# real ControlPlane re-validation returns). Proves:
#   * a valid, re-validated authority allows execution and audits BEFORE the side effect;
#   * every fail-closed deny path denies BEFORE the side effect;
#   * the boundary audit chain replay-verifies;
#   * a Sentinel advisory "safe" cannot authorize without ControlPlane authority.
#
# Produces the required artifacts and a verdict.json. Creates no tags, runs no
# deploy, exposes no secrets. Honors the golden-path env contract: when
# CLAW_GOLDENPATH_EVIDENCE_DIR is set, artifacts (incl. claw_audit_event.json and
# claw_context.json consumed by the Sentinel stage) are written there.
set -euo pipefail

# Resolve the repo root from the SCRIPT's own location, not the caller's CWD.
# The cross-product golden path invokes this script by absolute path from a
# non-git working directory (integration/ is workspace-level, not a git repo), so
# a CWD-based `git rev-parse` would fail. CI_PROJECT_DIR overrides when set.
REPO_ROOT="${CI_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$REPO_ROOT"

RUN_ID="${CLAW_RUN_ID:-claw-boundary-$(date -u +%Y%m%dT%H%M%SZ)}"
CORRELATION_ID="${CLAW_CORRELATION_ID:-$RUN_ID}"
EVIDENCE_DIR="${CLAW_GOLDENPATH_EVIDENCE_DIR:-$REPO_ROOT/artifacts/claw-runtime-boundary/$RUN_ID}"
mkdir -p "$EVIDENCE_DIR"

# Resolve a working python (venv script shebangs may be stale; the interpreter is fine).
PY="$REPO_ROOT/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

echo "== Claw runtime boundary integration proof =="
echo "  run_id=$RUN_ID correlation_id=$CORRELATION_ID"
echo "  evidence_dir=$EVIDENCE_DIR"

CLAW_EVIDENCE_DIR="$EVIDENCE_DIR" \
CLAW_RUN_ID="$RUN_ID" \
CLAW_CORRELATION_ID="$CORRELATION_ID" \
CLAW_TENANT_ID="${CLAW_TENANT_ID:-t1}" \
CLAW_APPROVAL_ID="${CLAW_APPROVAL_ID:-dec-1}" \
PYTHONPATH="$REPO_ROOT/src" "$PY" "$REPO_ROOT/scripts/integration/_claw_boundary_proof.py"
rc=$?

echo "== Artifact check =="
required=(
  claw_runtime_boundary.json
  claw_authority_validation.json
  claw_audit_chain.jsonl
  claw_audit_chain_verification.json
  sentinel_ingest_result.json
  verdict.json
)
missing=0
for f in "${required[@]}"; do
  if [ -s "$EVIDENCE_DIR/$f" ]; then echo "  [OK] $f"; else echo "  [MISSING] $f"; missing=1; fi
done
# Golden-path Sentinel stage consumes these two names from the claw-boundary dir.
for f in claw_audit_event.json claw_context.json; do
  [ -s "$EVIDENCE_DIR/$f" ] && echo "  [OK] $f" || { echo "  [MISSING] $f"; missing=1; }
done

verdict="$("$PY" -c "import json,sys; print(json.load(open('$EVIDENCE_DIR/verdict.json')).get('verdict','FAIL'))" 2>/dev/null || echo FAIL)"
echo "verdict=$verdict missing=$missing rc=$rc"
if [ "$rc" -ne 0 ] || [ "$missing" -ne 0 ] || [ "$verdict" != "PASS" ]; then
  echo "CLAW RUNTIME BOUNDARY: FAIL"
  exit 1
fi
echo "CLAW RUNTIME BOUNDARY: PASS (real_runtime_claw_verified)"
