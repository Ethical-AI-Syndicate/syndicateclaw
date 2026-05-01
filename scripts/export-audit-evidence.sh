#!/usr/bin/env sh
set -eu

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
work_dir="${TMPDIR:-/tmp}/audit-evidence-${timestamp}-$$"
payload_dir="$work_dir/payload"
mkdir -p "$payload_dir/files"

hash_cmd() { if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi; }

find . -path './.git' -prune -o -path './.venv' -prune -o -path './.cache' -prune -o \
  \( -name '*audit*.log' -o -name '*audit*.json' -o -name '*audit*.jsonl' \) -type f -print |
while IFS= read -r file; do
  safe_name="$(printf '%s' "$file" | sed 's#^\./##; s#[/ ]#_#g')"
  cp "$file" "$payload_dir/files/$safe_name"
done

if [ -n "${SYNDICATECLAW_DATABASE_URL:-}" ] && command -v psql >/dev/null 2>&1; then
  db_url="$(printf '%s' "$SYNDICATECLAW_DATABASE_URL" | sed 's#postgresql+asyncpg://#postgresql://#')"
  psql "$db_url" -c "\copy (select * from audit_events order by created_at) to '$payload_dir/files/audit_events.csv' csv header" || true
fi

manifest="$payload_dir/manifest.jsonl"
: > "$manifest"
printf '{"generated_at_utc":"%s","repo":"syndicateclaw","git_sha":"%s"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(git rev-parse HEAD 2>/dev/null || printf unknown)" >> "$manifest"
find "$payload_dir/files" -type f -print | sort | while IFS= read -r file; do
  printf '{"path":"%s","sha256":"%s","bytes":%s}\n' "${file#$payload_dir/}" "$(hash_cmd "$file" | awk '{print $1}')" "$(wc -c < "$file" | tr -d ' ')" >> "$manifest"
done
printf '%s\n' 'Chain-of-custody hashes only; source storage immutability is not asserted.' > "$payload_dir/README.txt"
archive="$work_dir/audit-evidence-${timestamp}.tar.gz"
tar -czf "$archive" -C "$work_dir" payload

target="${AUDIT_EXPORT_TARGET:-file://$PWD/audit-evidence-${timestamp}.tar.gz}"
case "$target" in
  file://*) dest="${target#file://}"; case "$dest" in */) mkdir -p "$dest"; dest="${dest%/}/audit-evidence-${timestamp}.tar.gz" ;; esac; mkdir -p "$(dirname "$dest")"; cp "$archive" "$dest"; printf 'PASS: wrote %s\n' "$dest" ;;
  s3://*) command -v aws >/dev/null 2>&1 || { printf 'FAIL: AUDIT_EXPORT_TARGET is s3:// but aws CLI is not installed\n' >&2; exit 1; }; aws s3 cp "$archive" "$target"; printf 'PASS: uploaded %s\n' "$target" ;;
  *) printf 'FAIL: unsupported AUDIT_EXPORT_TARGET %s\n' "$target" >&2; exit 1 ;;
esac
