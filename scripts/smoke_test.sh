#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${1:?Usage: smoke_test.sh <base_url>}"

echo "Running smoke tests against $BASE_URL"

# Health check
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/healthz")
if [ "$STATUS" != "200" ]; then
  echo "FAIL: /healthz returned $STATUS (expected 200)"
  exit 1
fi
echo "PASS: /healthz"

# Readiness check
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/readyz")
if [ "$STATUS" != "200" ]; then
  echo "FAIL: /readyz returned $STATUS (expected 200)"
  exit 1
fi
echo "PASS: /readyz"

# API info endpoint
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/api/v1/info")
if [ "$STATUS" != "200" ]; then
  echo "FAIL: /api/v1/info returned $STATUS (expected 200)"
  exit 1
fi
echo "PASS: /api/v1/info"

# Metrics endpoint
STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/metrics")
if [ "$STATUS" != "200" ]; then
  echo "FAIL: /metrics returned $STATUS (expected 200)"
  exit 1
fi
echo "PASS: /metrics"

echo "All smoke tests passed"
