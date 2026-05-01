#!/usr/bin/env sh
set -eu

hash_file() {
  [ -f "$1" ] || return 0
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi
}

printf 'repo=syndicateclaw\n'
printf 'git_sha=%s\n' "$(git rev-parse HEAD 2>/dev/null || printf unknown)"
printf 'git_ref=%s\n' "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || printf unknown)"
printf 'app_version=%s\n' "${RELEASE_VERSION:-${CI_COMMIT_TAG:-unknown}}"
printf 'image_tag=%s\n' "${IMAGE_TAG:-${CI_REGISTRY_IMAGE:-unknown}}"
printf 'selected_env_names='
env | cut -d= -f1 | grep -E '^(SYNDICATECLAW|AUTH_|OIDC_|JWT_|OTEL_|LOG_|APP_ENV|RELEASE_VERSION|IMAGE_TAG)' | sort | paste -sd ',' -
printf 'config_hashes:\n'
for f in pyproject.toml uv.lock Dockerfile deploy/k8s/deployment.yaml deploy/k8s/secret.yaml alembic.ini; do
  hash_file "$f" | sed 's/^/  /'
done
printf 'migration_version=%s\n' "${MIGRATION_VERSION:-unknown}"
