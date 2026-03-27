"""Minimal pytest-benchmark smoke so scheduled CI can emit JSON for regression checks."""

from __future__ import annotations


def _noop() -> None:
    pass


def test_benchmark_smoke(benchmark) -> None:
    benchmark(_noop)
