#!/usr/bin/env sh
set -eu

out="${1:-sbom.spdx.json}"

if command -v syft >/dev/null 2>&1; then
  syft dir:. -o spdx-json="$out"
  echo "Wrote $out with syft"
  exit 0
fi

printf '{\n' > "$out"
printf '  "spdxVersion": "SPDX-2.3",\n' >> "$out"
printf '  "dataLicense": "CC0-1.0",\n' >> "$out"
printf '  "SPDXID": "SPDXRef-DOCUMENT",\n' >> "$out"
printf '  "name": "%s-fallback-inventory",\n' "$(basename "$(pwd)")" >> "$out"
printf '  "documentNamespace": "urn:local:%s:%s",\n' "$(basename "$(pwd)")" "$(date -u +%Y%m%dT%H%M%SZ)" >> "$out"
printf '  "creationInfo": {"created": "%s", "creators": ["Tool: scripts/generate-sbom.sh"]},\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$out"
printf '  "packages": []\n' >> "$out"
printf '}\n' >> "$out"
echo "Wrote fallback dependency inventory to $out because syft was unavailable"
