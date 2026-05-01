#!/usr/bin/env sh
set -eu

report="${1:-dependency-audit-report.json}"
warnings=""

if [ -f pyproject.toml ]; then
  if command -v pip-audit >/dev/null 2>&1; then
    pip-audit -f json -o pip-audit.json 2>pip-audit.stderr || warnings="${warnings}pip-audit-findings-or-error;"
  else
    warnings="${warnings}pip-audit-unavailable;"
  fi
fi

if [ -f console/package-lock.json ] && command -v npm >/dev/null 2>&1; then
  npm --prefix console audit --omit=dev --json > npm-audit-console.json 2>npm-audit-console.stderr || warnings="${warnings}npm-audit-console-findings-or-error;"
elif [ -f console/package-lock.json ]; then
  warnings="${warnings}npm-unavailable-console;"
fi

printf '{\n' > "$report"
printf '  "generated_at": "%s",\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$report"
printf '  "mode": "non_blocking_evidence",\n' >> "$report"
printf '  "warnings": "%s",\n' "$warnings" >> "$report"
printf '  "artifacts": ["pip-audit.json", "npm-audit-console.json"]\n' >> "$report"
printf '}\n' >> "$report"

echo "Wrote $report"
