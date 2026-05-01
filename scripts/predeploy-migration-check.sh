#!/usr/bin/env sh
set -eu

migration_dir="${MIGRATION_DIR:-migrations/versions}"

if [ ! -d "$migration_dir" ]; then
  echo "FAIL: migration directory not found: $migration_dir"
  exit 1
fi

if [ "${CI:-}" = "true" ]; then
  if [ "${BACKUP_CONFIRMED:-}" != "true" ]; then
    echo "FAIL: set BACKUP_CONFIRMED=true in CI after verifying a restorable database backup."
    exit 1
  fi
elif [ "${BACKUP_CONFIRMED:-}" != "true" ]; then
  if [ -t 0 ]; then
    printf "Confirm a restorable database backup exists before migration (yes/no): "
    read answer
    [ "$answer" = "yes" ] || { echo "FAIL: backup confirmation declined"; exit 1; }
  else
    echo "FAIL: non-interactive run requires BACKUP_CONFIRMED=true."
    exit 1
  fi
fi

echo "PASS: migration directory exists: $migration_dir"
if command -v python >/dev/null 2>&1; then
  python -m alembic heads || echo "WARN: alembic heads unavailable; ensure dependencies and DB config are installed before deploy."
  python -m alembic current || echo "WARN: alembic current unavailable without database connectivity; run it in the target predeploy environment."
else
  echo "WARN: python unavailable; cannot run Alembic status commands."
fi

if rg -n "drop_table|drop_column|DROP TABLE|DROP COLUMN|TRUNCATE|DELETE FROM|op.execute\\(" "$migration_dir" >/tmp/syndicateclaw-migration-risk.txt 2>/dev/null; then
  echo "WARN: potentially irreversible migration statements detected:"
  cat /tmp/syndicateclaw-migration-risk.txt
else
  echo "PASS: no obvious irreversible migration statements detected heuristically."
fi

echo "Rollback prerequisites: verified backup, previous image tag, Alembic revision map, and customer approval to restore or apply compensating migrations."
