#!/usr/bin/env python3
"""Compare pytest-benchmark JSON to a baseline; fail if any metric regresses >10%."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


MAX_REGRESSION_RATIO = 1.10
MIN_ABSOLUTE_REGRESSION_SECONDS = 0.000_005


def _mean_seconds(bench: dict[str, Any]) -> float | None:
    stats = bench.get("stats") or {}
    return stats.get("mean")


def main() -> int:
    if len(sys.argv) != 3:
        print(
            "Usage: check_benchmark_regression.py <current.json> <baseline.json>",
            file=sys.stderr,
        )
        return 2
    cur_path = Path(sys.argv[1])
    base_path = Path(sys.argv[2])
    if not cur_path.exists():
        print("Current benchmark JSON missing; skip.", file=sys.stderr)
        return 0
    if not base_path.exists():
        print("Baseline missing; skip.", file=sys.stderr)
        return 0
    base_raw = json.loads(base_path.read_text(encoding="utf-8"))
    if isinstance(base_raw, dict) and base_raw.get("note", "").startswith("PENDING"):
        print("Baseline placeholder — skip comparison.")
        return 0

    current = json.loads(cur_path.read_text(encoding="utf-8"))
    baseline = base_raw

    benches_cur = {b["fullname"]: b for b in current.get("benchmarks", [])}
    benches_base = {b["fullname"]: b for b in baseline.get("benchmarks", [])}

    regressions = 0
    for name, b_cur in benches_cur.items():
        b_base = benches_base.get(name)
        if b_base is None:
            continue
        m_cur = _mean_seconds(b_cur)
        m_base = _mean_seconds(b_base)
        if m_cur is None or m_base is None or m_base <= 0:
            continue
        if (
            m_cur > m_base * MAX_REGRESSION_RATIO
            and (m_cur - m_base) > MIN_ABSOLUTE_REGRESSION_SECONDS
        ):
            pct = (m_cur / m_base - 1) * 100
            print(f"REGRESSION {name}: {m_cur:.4f}s vs baseline {m_base:.4f}s (+{pct:.1f}%)")
            regressions += 1

    if regressions:
        return 1
    print("Benchmark comparison: within 10% of baseline (or no comparable entries).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
