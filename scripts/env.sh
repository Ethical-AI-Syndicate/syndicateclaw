#!/usr/bin/env bash
# Usage: source scripts/env.sh <environment>
#   e.g. source scripts/env.sh staging
#
# Loads .env.<environment> and exports SYNDICATECLAW_ENV so that
# Settings(), alembic, and the seed script all target the right database.
#
# Environment isolation:
#   dev:     DB=syndicateclaw_dev      Redis=db1  API=:8001
#   staging: DB=syndicateclaw_staging  Redis=db2  API=:8002
#   prod:    DB=syndicateclaw_prod     Redis=db3  API=:8000

set -euo pipefail

ENV_NAME="${1:?Usage: source scripts/env.sh <dev|staging|prod>}"
ENV_FILE=".env.${ENV_NAME}"

if [ ! -f "${ENV_FILE}" ]; then
    echo "ERROR: ${ENV_FILE} not found" >&2
    return 1 2>/dev/null || exit 1
fi

export SYNDICATECLAW_ENV="${ENV_NAME}"

# Export all non-comment, non-empty lines as environment variables
while IFS= read -r line; do
    line="${line%%#*}"       # strip inline comments
    line="${line#"${line%%[![:space:]]*}"}"  # trim leading whitespace
    [ -z "$line" ] && continue
    export "$line"
done < "${ENV_FILE}"

echo "Environment: ${ENV_NAME}"
echo "  Database:  ${SYNDICATECLAW_DATABASE_URL:-<not set>}"
echo "  Redis:     ${SYNDICATECLAW_REDIS_URL:-<not set>}"
echo "  API port:  ${SYNDICATECLAW_API_PORT:-<not set>}"
