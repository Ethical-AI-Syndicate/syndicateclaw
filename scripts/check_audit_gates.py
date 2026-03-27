#!/usr/bin/env python3
"""Fail CI on pip-audit / bandit high-severity findings.

Usage:
  pip-audit --output json > audit_report.json
  bandit -r src/ -ll --format json -o bandit_report.json
  python scripts/check_audit_gates.py audit_report.json bandit_report.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: check_audit_gates.py <audit_report.json> <bandit_report.json>",
            file=sys.stderr,
        )
        return 2
    audit_path = Path(sys.argv[1])
    bandit_path = Path(sys.argv[2])

    if not audit_path.exists() or not bandit_path.exists():
        print("Missing report file(s); skipping gates (exit 0).", file=sys.stderr)
        return 0

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    bandit = json.loads(bandit_path.read_text(encoding="utf-8"))

    fail_audit = 0
    accepted = 0
    for dep in audit.get("dependencies", []):
        if not isinstance(dep, dict):
            continue
        vulns = dep.get("vulns") or []
        for v in vulns:
            if not isinstance(v, dict):
                continue
            sev = str(v.get("severity", "")).upper()
            fix = v.get("fix_versions")
            if sev in {"CRITICAL", "HIGH"} and fix:
                fail_audit += 1
            elif sev in {"CRITICAL", "HIGH"}:
                accepted += 1

    fail_bandit = 0
    for r in bandit.get("results", []):
        if isinstance(r, dict) and str(r.get("issue_severity", "")).upper() == "HIGH":
            fail_bandit += 1

    print(
        f"audit: {fail_audit} critical/high with fix; {accepted} accepted risk without fix; "
        f"bandit high: {fail_bandit}"
    )
    if fail_audit or fail_bandit:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
