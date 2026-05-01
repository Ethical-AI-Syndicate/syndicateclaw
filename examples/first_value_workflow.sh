#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${SYNDICATECLAW_BASE_URL:-http://localhost:8000}"
API_KEY="${SYNDICATECLAW_API_KEY:-}"

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "FAIL missing required command: $1" >&2
    exit 1
  }
}

need curl
need python3

auth_args=()
if [ -n "$API_KEY" ]; then
  auth_args=(-H "X-API-Key: $API_KEY")
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

echo "Checking SyndicateClaw health at $BASE_URL/healthz"
curl -fsS "$BASE_URL/healthz" >"$tmpdir/health.json"
cat "$tmpdir/health.json"
echo

cat >"$tmpdir/workflow.json" <<'JSON'
{
  "name": "first-value-approval-demo",
  "version": "1.0.0",
  "description": "Minimal workflow definition used to prove API access and persistence.",
  "nodes": [
    {
      "id": "start",
      "name": "Start",
      "node_type": "START",
      "handler": "builtin.start",
      "config": {}
    },
    {
      "id": "end",
      "name": "End",
      "node_type": "END",
      "handler": "builtin.end",
      "config": {}
    }
  ],
  "edges": [
    {
      "source_node_id": "start",
      "target_node_id": "end"
    }
  ],
  "metadata": {
    "source": "examples/first_value_workflow.sh"
  }
}
JSON

echo "Creating workflow"
curl -fsS -X POST "$BASE_URL/api/v1/workflows/" \
  "${auth_args[@]}" \
  -H "Content-Type: application/json" \
  --data-binary @"$tmpdir/workflow.json" >"$tmpdir/workflow-response.json"
cat "$tmpdir/workflow-response.json"
echo

workflow_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$tmpdir/workflow-response.json")"

cat >"$tmpdir/run.json" <<'JSON'
{
  "initial_state": {
    "objective": "Analyze uploaded portfolio positions and draft risk memo.",
    "risk_level": "HIGH",
    "approval_expected": true
  },
  "tags": {
    "demo": "first-value"
  }
}
JSON

echo "Starting workflow run"
curl -fsS -X POST "$BASE_URL/api/v1/workflows/$workflow_id/runs" \
  "${auth_args[@]}" \
  -H "Content-Type: application/json" \
  --data-binary @"$tmpdir/run.json" >"$tmpdir/run-response.json"
cat "$tmpdir/run-response.json"
echo

run_id="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["id"])' "$tmpdir/run-response.json")"

echo "Fetching run"
curl -fsS "$BASE_URL/api/v1/workflows/runs/$run_id" \
  "${auth_args[@]}" >"$tmpdir/run-fetch.json"
cat "$tmpdir/run-fetch.json"
echo

echo "PASS first workflow value path completed: workflow_id=$workflow_id run_id=$run_id"
