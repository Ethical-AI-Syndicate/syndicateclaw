"""Durable Claw audit chain tests (SDD-CLAW-DURABLE-EXECUTOR-BOUNDARY-002).

Encodes the production durability behavior the golden-path validator requires:
file-backed fsync append chain, restart replay, concurrent-append safety, and
corrupt-tail fail-closed. These are real behaviors, not asserted flags.
"""

from __future__ import annotations

import json
import threading

from syndicateclaw.runtime_boundary.durable_audit import (
    GENESIS,
    DurableAuditChain,
    reopen,
)


def test_append_is_durable_and_linked(tmp_path):
    chain = DurableAuditChain(tmp_path / "audit.jsonl")
    s0, h0 = chain.append({"decision": "allow", "n": 0})
    s1, h1 = chain.append({"decision": "deny", "n": 1})
    assert (s0, s1) == (0, 1)
    recs = chain.records()
    assert recs[0]["previous_hash"] == GENESIS
    assert recs[1]["previous_hash"] == h0
    assert recs[1]["event_hash"] == h1
    # The file physically exists with two JSONL lines.
    lines = (tmp_path / "audit.jsonl").read_text().splitlines()
    assert len(lines) == 2


def test_restart_replay_verifies(tmp_path):
    p = tmp_path / "audit.jsonl"
    chain = DurableAuditChain(p)
    for i in range(5):
        chain.append({"decision": "allow", "n": i})
    # Simulate a process restart: brand-new object reading the same file.
    restarted = reopen(p)
    result = restarted.verify()
    assert result.valid is True
    assert result.record_count == 5
    assert result.genesis_linked is True
    assert result.corrupt_tail is False


def test_corrupt_tail_fails_closed(tmp_path):
    p = tmp_path / "audit.jsonl"
    chain = DurableAuditChain(p)
    chain.append({"decision": "allow", "n": 0})
    chain.append({"decision": "allow", "n": 1})
    # Corrupt the tail: append a garbage (unparsable) line, as a torn write would.
    with p.open("a", encoding="utf-8") as f:
        f.write('{"decision": "allow", "n": 2  <<TORN\n')
    result = reopen(p).verify()
    assert result.valid is False
    assert result.corrupt_tail is True


def test_tampered_record_fails_closed(tmp_path):
    p = tmp_path / "audit.jsonl"
    chain = DurableAuditChain(p)
    chain.append({"decision": "allow", "n": 0})
    chain.append({"decision": "allow", "n": 1})
    # Tamper an earlier record's content without fixing the hash.
    lines = p.read_text().splitlines()
    rec0 = json.loads(lines[0])
    rec0["decision"] = "TAMPERED"
    lines[0] = json.dumps(rec0, sort_keys=True)
    p.write_text("\n".join(lines) + "\n")
    result = reopen(p).verify()
    assert result.valid is False


def test_concurrent_appends_do_not_fork_chain(tmp_path):
    p = tmp_path / "audit.jsonl"
    chain = DurableAuditChain(p)
    n_threads, per = 8, 10

    def worker(tid):
        c = reopen(p)  # each thread its own handle, shared file + flock
        for i in range(per):
            c.append({"decision": "allow", "tid": tid, "i": i})

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    result = reopen(p).verify()
    assert result.valid is True, result.detail
    assert result.record_count == n_threads * per
    # Sequences are a contiguous 0..N-1 with no gaps or dupes (no fork).
    seqs = sorted(r["sequence"] for r in reopen(p).records())
    assert seqs == list(range(n_threads * per))


def test_append_failure_raises_before_write(tmp_path):
    p = tmp_path / "audit.jsonl"
    chain = DurableAuditChain(p)
    chain.append({"decision": "allow", "n": 0})
    chain.set_fail(True)
    try:
        chain.append({"decision": "allow", "n": 1})
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    # The failed append wrote nothing: still exactly one record, chain valid.
    assert reopen(p).verify().record_count == 1
