#!/usr/bin/env sh
set -eu

cat <<'EOF'
Restore drill checklist for syndicateclaw

1. Capture ticket, release/version, operator, UTC start time, and target environment.
2. Confirm PostgreSQL backup ID, Redis role, provider credentials, signing keys, and encryption key versions.
3. Restore into an isolated database/namespace first; do not overwrite production during the drill.
4. Run Alembic status/current checks before any upgrade command.
5. Execute smoke checks:
   - /healthz and /readyz
   - JWT/API-key auth path
   - workflow read path
   - audit query/export path
6. Capture evidence:
   - backup metadata and checksum
   - restore transcript
   - migration status
   - smoke test output
7. Document rollback decision criteria and customer SRE sign-off.
EOF
