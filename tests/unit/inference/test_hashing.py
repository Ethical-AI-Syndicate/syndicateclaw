from syndicateclaw.inference.hashing import canonical_json_hash


def test_canonical_hash_stable_under_key_reorder() -> None:
    a = {"z": 1, "a": 2, "m": {"b": 3, "a": 4}}
    b = {"a": 2, "m": {"a": 4, "b": 3}, "z": 1}
    assert canonical_json_hash(a) == canonical_json_hash(b)


def test_canonical_hash_differs_for_different_payloads() -> None:
    assert canonical_json_hash({"x": 1}) != canonical_json_hash({"x": 2})
