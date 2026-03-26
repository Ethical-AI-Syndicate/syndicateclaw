#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# env-teardown.sh — Destroy an ephemeral SyndicateClaw review environment
#
# Usage:
#   ./scripts/env-teardown.sh <mr-iid>
#
# Cleans up:
#   - SSH reverse tunnel
#   - Nginx config on GCP host
#   - Cloudflare DNS record
#   - Application container
#   - PostgreSQL database
# ─────────────────────────────────────────────────────────
set -euo pipefail

MR_IID="${1:?Usage: env-teardown.sh <mr-iid>}"

# ─── Config ─────────────────────────────────────────────
GCP_HOST="${GCP_HOST:?Set GCP_HOST}"
GCP_USER="${GCP_USER:-root}"
GCP_SSH_KEY="${GCP_SSH_KEY:?Set GCP_SSH_KEY}"
GCP_NGINX_DIR="${GCP_NGINX_CONF_DIR:-/etc/nginx/sites-enabled}"
CLOUDFLARE_ZONE="${CLOUDFLARE_ZONE_ID:?Set CLOUDFLARE_ZONE_ID}"
CLOUDFLARE_TOKEN="${CLOUDFLARE_API_TOKEN:?Set CLOUDFLARE_API_TOKEN}"
PG_HOST="localhost"
PG_USER="syndicateclaw"

ENV_NAME="pr-${MR_IID}"
STATE_FILE="/tmp/syndicateclaw-review-${ENV_NAME}.json"

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -i ${GCP_SSH_KEY}"

echo "🧹 Tearing down review environment for MR #${MR_IID}..."

# ─── 1. Remove Nginx config on GCP ────────────────────
echo "🌐 Removing Nginx config..."
ssh $SSH_OPTS "${GCP_USER}@${GCP_HOST}" \
    "rm -f ${GCP_NGINX_DIR}/${ENV_NAME}.conf && nginx -s reload" 2>/dev/null || echo "  ⚠ Nginx config not found"

# ─── 2. Kill SSH tunnel ────────────────────────────────
echo "🔗 Closing SSH tunnel..."
# Find and kill the tunnel process
pkill -f "ssh.*${GCP_HOST}.*${MR_IID}" 2>/dev/null || echo "  ⚠ No tunnel process found"

# ─── 3. Remove Cloudflare DNS record ──────────────────
if [ -f "$STATE_FILE" ]; then
    CF_ID=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['cf_record_id'])" 2>/dev/null || echo "")
    if [ -n "$CF_ID" ] && [ "$CF_ID" != "unknown" ]; then
        echo "📡 Removing DNS record..."
        curl -sf -X DELETE \
            "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE}/dns_records/${CF_ID}" \
            -H "Authorization: Bearer ${CLOUDFLARE_TOKEN}" > /dev/null 2>&1
        echo "  ✓ DNS record removed"
    fi
fi

# ─── 4. Stop and remove container ──────────────────────
echo "🛑 Stopping container..."
docker stop "syndicateclaw-${ENV_NAME}" 2>/dev/null || true
docker rm "syndicateclaw-${ENV_NAME}" 2>/dev/null || true
echo "  ✓ Container removed"

# ─── 5. Drop PostgreSQL database ───────────────────────
DB_NAME="review_pr_${MR_IID}"
echo "📦 Dropping database..."
docker exec syndicateclaw-postgres psql -U "$PG_USER" -c "DROP DATABASE IF EXISTS $DB_NAME;" 2>/dev/null || true
echo "  ✓ Database dropped"

# ─── 6. Clean up state file ────────────────────────────
rm -f "$STATE_FILE"

echo ""
echo "✅ Review environment destroyed (MR #${MR_IID})"
