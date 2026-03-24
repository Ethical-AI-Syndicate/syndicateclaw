"""Tests for bounded policy cache."""

from __future__ import annotations

from syndicateclaw.inference.policy_gates import BoundedPolicyCache


def test_policy_cache_ttl_and_lru_cap() -> None:
    c = BoundedPolicyCache(ttl_seconds=10.0, max_entries=2)
    t = 0.0
    c.set("a", "allow", now=t)
    c.set("b", "deny", now=t)
    c.set("c", "allow", now=t)
    assert c.get("a", now=t) is None
    assert c.get("b", now=t) == "deny"
    assert c.get("c", now=t) == "allow"
