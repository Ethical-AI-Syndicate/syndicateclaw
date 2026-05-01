#!/usr/bin/env sh
set -eu

out="${1:-provenance-evidence.json}"
repo="${CI_PROJECT_PATH:-$(basename "$(pwd)")}"
commit="${CI_COMMIT_SHA:-$(git rev-parse HEAD 2>/dev/null || echo unknown)}"
ref="${CI_COMMIT_REF_NAME:-$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)}"
builder="${CI_JOB_IMAGE:-${CI_RUNNER_DESCRIPTION:-local-shell}}"
timestamp="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

printf '{\n' > "$out"
printf '  "repo": "%s",\n' "$repo" >> "$out"
printf '  "commit_sha": "%s",\n' "$commit" >> "$out"
printf '  "ref": "%s",\n' "$ref" >> "$out"
printf '  "build_timestamp_utc": "%s",\n' "$timestamp" >> "$out"
printf '  "builder": "%s",\n' "$builder" >> "$out"
printf '  "lockfile_hashes": {\n' >> "$out"

first=1
for file in uv.lock poetry.lock requirements.txt console/package-lock.json sdk/poetry.lock sdk/uv.lock; do
  if [ -f "$file" ]; then
    hash="$(sha256sum "$file" | awk '{print $1}')"
    if [ "$first" -eq 0 ]; then
      printf ',\n' >> "$out"
    fi
    first=0
    printf '    "%s": "sha256:%s"' "$file" "$hash" >> "$out"
  fi
done

printf '\n  }\n}\n' >> "$out"
echo "Wrote $out"
