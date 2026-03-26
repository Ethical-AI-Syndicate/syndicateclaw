#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# env-provision.sh — Spin up an ephemeral SyndicateClaw review environment
#
# Usage:
#   ./scripts/env-provision.sh <mr-iid> <commit-sha> [--deploy]
#
# Creates:
#   - Postgres database
#   - Application container on a free port
#   - SSH reverse tunnel to GCP host
#   - Nginx config on GCP host
#   - Cloudflare DNS record (DNS-only, no proxy)
#
# Requires:
#   - SYNDICATECLAW_IMAGE         (default: registry.mikeholownych.com/ai-syndicate/syndicateclaw:latest)
#   - GCP_HOST                    (GCP proxy host, e.g. proxy.mikeholownych.com)
#   - GCP_USER                    (SSH user on GCP host, default: root)
#   - GCP_SSH_KEY                 (path to SSH key for GCP host)
#   - GCP_NGINX_CONF_DIR          (nginx config dir on GCP, default: /etc/nginx/sites-enabled)
#   - CLOUDFLARE_ZONE_ID          (Cloudflare DNS zone)
#   - CLOUDFLARE_API_TOKEN        (Cloudflare API token with DNS write scope)
#   - ENV_DOMAIN                  (base domain, default: syndicateclaw.mikeholownych.com)
# ─────────────────────────────────────────────────────────
set -euo pipefail

MR_IID="${1:?Usage: env-provision.sh <mr-iid> <commit-sha>}"
COMMIT_SHA="${2:?Usage: env-provision.sh <mr-iid> <commit-sha>}"
DEPLOY="${3:-}"

# ─── Config ─────────────────────────────────────────────
IMAGE="${SYNDICATECLAW_IMAGE:-registry.mikeholownych.com/ai-syndicate/syndicateclaw:$COMMIT_SHA}"
GCP_HOST="${GCP_HOST:?Set GCP_HOST}"
GCP_USER="${GCP_USER:-root}"
GCP_SSH_KEY="${GCP_SSH_KEY:?Set GCP_SSH_KEY}"
GCP_NGINX_DIR="${GCP_NGINX_CONF_DIR:-/etc/nginx/sites-enabled}"
CLOUDFLARE_ZONE="${CLOUDFLARE_ZONE_ID:?Set CLOUDFLARE_ZONE_ID}"
CLOUDFLARE_TOKEN="${CLOUDFLARE_API_TOKEN:?Set CLOUDFLARE_API_TOKEN}"
DOMAIN="${ENV_DOMAIN:-syndicateclaw.mikeholownych.com}"

ENV_NAME="pr-${MR_IID}"
SUBDOMAIN="${ENV_NAME}.${DOMAIN}"
DB_NAME="review_pr_${MR_IID}"
PG_HOST="localhost"
PG_PORT="5432"
PG_USER="syndicateclaw"
PG_PASS="syndicateclaw"
REDIS_HOST="localhost"
REDIS_DB="$((5 + MR_IID % 50))"  # 5-54 reserved for review envs
SECRET_KEY=$(openssl rand -hex 32)

SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -i ${GCP_SSH_KEY}"

# ─── Find a free port ──────────────────────────────────
find_free_port() {
    for port in $(seq 8010 8099); do
        if ! ss -tln | grep -q ":${port} "; then
            echo "$port"
            return
        fi
    done
    echo "ERROR: No free ports in 8010-8099" >&2
    exit 1
}

PORT=$(find_free_port)
echo "🔧 Provisioning review environment:"
echo "   MR:       #$MR_IID"
echo "   Commit:   $COMMIT_SHA"
echo "   Port:     $PORT"
echo "   Subdomain: $SUBDOMAIN"
echo "   Database:  $DB_NAME"

# ─── 1. Create PostgreSQL database ─────────────────────
echo "📦 Creating database..."
docker exec syndicateclaw-postgres psql -U "$PG_USER" -c "CREATE DATABASE $DB_NAME OWNER $PG_USER;" 2>/dev/null || true
echo "  ✓ Database $DB_NAME ready"

# ─── 2. Run migrations ─────────────────────────────────
echo "📦 Running migrations..."
docker run --rm \
    --network syndicateclaw-net \
    -e SYNDICATECLAW_DATABASE_URL="postgresql+asyncpg://${PG_USER}:${PG_PASS}@${PG_HOST}:${PG_PORT}/${DB_NAME}" \
    -e SYNDICATECLAW_SECRET_KEY="$SECRET_KEY" \
    -e SYNDICATECLAW_ENVIRONMENT="development" \
    "$IMAGE" alembic upgrade head
echo "  ✓ Migrations applied"

# ─── 3. Start application container ────────────────────
echo "🚀 Starting container..."
docker run -d \
    --name "syndicateclaw-${ENV_NAME}" \
    --network syndicateclaw-net \
    -p "${PORT}:8000" \
    -e SYNDICATECLAW_DATABASE_URL="postgresql+asyncpg://${PG_USER}:${PG_PASS}@${PG_HOST}:${PG_PORT}/${DB_NAME}" \
    -e SYNDICATECLAW_REDIS_URL="redis://${REDIS_HOST}:6379/${REDIS_DB}" \
    -e SYNDICATECLAW_SECRET_KEY="$SECRET_KEY" \
    -e SYNDICATECLAW_ENVIRONMENT="development" \
    -e SYNDICATECLAW_LOG_LEVEL="DEBUG" \
    --restart unless-stopped \
    "$IMAGE"
echo "  ✓ Container syndicateclaw-${ENV_NAME} running on port ${PORT}"

# ─── 4. Wait for health check ──────────────────────────
echo "⏳ Waiting for health check..."
for i in $(seq 1 30); do
    if curl -sf "http://localhost:${PORT}/healthz" > /dev/null 2>&1; then
        echo "  ✓ Healthy"
        break
    fi
    sleep 2
done

# ─── 5. Create SSH reverse tunnel ──────────────────────
echo "🔗 Creating SSH reverse tunnel..."
ssh $SSH_OPTS -fN -R "${PORT}:localhost:${PORT}" "${GCP_USER}@${GCP_HOST}"
echo "  ✓ Tunnel ${PORT} → ${GCP_HOST}:${PORT}"

# ─── 6. Create Nginx config on GCP host ────────────────
echo "🌐 Creating Nginx config on GCP..."
NGINX_CONF=$(cat <<EOF
server {
    listen 443 ssl;
    server_name ${SUBDOMAIN};

    ssl_certificate     /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    location / {
        proxy_pass http://localhost:${PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF
)

echo "$NGINX_CONF" | ssh $SSH_OPTS "${GCP_USER}@${GCP_HOST}" "cat > ${GCP_NGINX_DIR}/${ENV_NAME}.conf && nginx -s reload"
echo "  ✓ Nginx configured for ${SUBDOMAIN}"

# ─── 7. Create Cloudflare DNS record (DNS-only, no proxy) ──
echo "📡 Creating DNS record..."
CF_RECORD=$(curl -sf -X POST \
    "https://api.cloudflare.com/client/v4/zones/${CLOUDFLARE_ZONE}/dns_records" \
    -H "Authorization: Bearer ${CLOUDFLARE_TOKEN}" \
    -H "Content-Type: application/json" \
    -d "{\"type\":\"CNAME\",\"name\":\"${ENV_NAME}\",\"content\":\"${GCP_HOST}\",\"ttl\":120,\"proxied\":false}" \
    2>&1)
CF_ID=$(echo "$CF_RECORD" | python3 -c "import sys,json; print(json.load(sys.stdin)['result']['id'])" 2>/dev/null || echo "unknown")
echo "  ✓ DNS record created (ID: $CF_ID)"

# ─── 8. Save state for teardown ────────────────────────
STATE_FILE="/tmp/syndicateclaw-review-${ENV_NAME}.json"
cat > "$STATE_FILE" <<EOF
{
    "mr_iid": ${MR_IID},
    "commit_sha": "${COMMIT_SHA}",
    "port": ${PORT},
    "subdomain": "${SUBDOMAIN}",
    "database": "${DB_NAME}",
    "container": "syndicateclaw-${ENV_NAME}",
    "nginx_conf": "${ENV_NAME}.conf",
    "cf_record_id": "${CF_ID}"
}
EOF
echo "  ✓ State saved to $STATE_FILE"

# ─── Summary ───────────────────────────────────────────
echo ""
echo "✅ Review environment ready!"
echo "   URL:      https://${SUBDOMAIN}"
echo "   Health:   https://${SUBDOMAIN}/healthz"
echo "   API Docs: https://${SUBDOMAIN}/docs"
echo "   Container: syndicateclaw-${ENV_NAME}"
echo "   Port:     ${PORT}"
echo ""
echo "Teardown: ./scripts/env-teardown.sh ${MR_IID}"
