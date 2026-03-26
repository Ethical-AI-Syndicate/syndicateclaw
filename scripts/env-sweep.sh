#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# env-sweep.sh — Clean up stale review environments (>24h old)
#
# Usage:
#   ./scripts/env-sweep.sh [--dry-run]
#
# Run via cron or CI schedule:
#   0 */4 * * * /path/to/env-sweep.sh
# ─────────────────────────────────────────────────────────
set -euo pipefail

DRY_RUN="${1:-}"
MAX_AGE_HOURS=24

echo "🧹 Sweeping stale review environments (older than ${MAX_AGE_HOURS}h)..."

for STATE_FILE in /tmp/syndicateclaw-review-pr-*.json; do
    [ -f "$STATE_FILE" ] || continue

    CONTAINER=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['container'])" 2>/dev/null || continue)
    MR_IID=$(python3 -c "import json; print(json.load(open('$STATE_FILE'))['mr_iid'])" 2>/dev/null || continue)

    # Check if container is still running and how old
    if docker inspect "$CONTAINER" > /dev/null 2>&1; then
        CREATED=$(docker inspect --format='{{.Created}}' "$CONTAINER" 2>/dev/null)
        CREATED_EPOCH=$(date -d "$CREATED" +%s 2>/dev/null || continue)
        NOW_EPOCH=$(date +%s)
        AGE_HOURS=$(( (NOW_EPOCH - CREATED_EPOCH) / 3600 ))

        if [ "$AGE_HOURS" -gt "$MAX_AGE_HOURS" ]; then
            echo "  🗑  MR #$MR_IID — ${AGE_HOURS}h old (container: $CONTAINER)"

            if [ "$DRY_RUN" = "--dry-run" ]; then
                echo "     (dry run — skipping)"
            else
                "$(dirname "$0")/env-teardown.sh" "$MR_IID"
            fi
        else
            echo "  ✓  MR #$MR_IID — ${AGE_HOURS}h old (still active)"
        fi
    else
        # Container gone but state file exists — clean up
        echo "  🗑  MR #$MR_IID — container missing, cleaning state"
        if [ "$DRY_RUN" != "--dry-run" ]; then
            rm -f "$STATE_FILE"
        fi
    fi
done

# Also check for orphaned containers
echo ""
echo "🔍 Checking for orphaned review containers..."
for CONTAINER in $(docker ps --filter "name=syndicateclaw-pr-" --format '{{.Names}}' 2>/dev/null); do
    MR_IID="${CONTAINER#syndicateclaw-pr-}"
    CREATED=$(docker inspect --format='{{.Created}}' "$CONTAINER" 2>/dev/null)
    CREATED_EPOCH=$(date -d "$CREATED" +%s 2>/dev/null || continue)
    NOW_EPOCH=$(date +%s)
    AGE_HOURS=$(( (NOW_EPOCH - CREATED_EPOCH) / 3600 ))

    if [ "$AGE_HOURS" -gt "$MAX_AGE_HOURS" ]; then
        echo "  🗑  Orphaned: $CONTAINER (${AGE_HOURS}h old)"
        if [ "$DRY_RUN" != "--dry-run" ]; then
            docker stop "$CONTAINER" 2>/dev/null || true
            docker rm "$CONTAINER" 2>/dev/null || true
        fi
    fi
done

echo ""
echo "✅ Sweep complete"
