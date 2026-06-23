"""Durable, fsync'd, append-only hash-chain audit ledger for the Claw runtime
boundary (SDD-CLAW-DURABLE-EXECUTOR-BOUNDARY-002).

The golden-path evidence validator requires the Claw boundary audit to be DURABLE,
not in-memory: a file-backed append-only JSONL hash chain that is fsync'd on every
append, replay-verifiable after a process restart, safe under concurrent appends,
and FAIL-CLOSED on a corrupt tail. This module provides exactly that.

Chain model (matches the platform convention):
  * one JSON record per line (JSONL);
  * genesis previous_hash = 64 zeros;
  * event_hash = sha256(previous_hash_bytes + canonical_record_without_hash);
  * each record links to the prior record's event_hash.

Durability:
  * each append writes the line, flushes, and ``os.fsync`` the file descriptor
    before returning, then fsyncs the directory entry;
  * a cross-process file lock (``fcntl.flock``) serializes appends so concurrent
    writers cannot interleave or fork the chain.

Fail-closed:
  * ``verify()`` returns a structured result; a corrupt/forked/truncated tail makes
    it INVALID. The boundary treats an unverifiable chain as deny (no side effect).
  * ``append`` re-reads the current tail under the lock so the previous_hash is
    always the durable last record, never a stale in-memory value.
"""

from __future__ import annotations

import dataclasses
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any

GENESIS = "0" * 64


def _canonical(record: dict[str, Any]) -> bytes:
    body = {k: v for k, v in record.items() if k != "event_hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(previous_hash: str, record: dict[str, Any]) -> str:
    return hashlib.sha256(previous_hash.encode("utf-8") + _canonical(record)).hexdigest()


@dataclasses.dataclass(frozen=True)
class VerifyResult:
    valid: bool
    record_count: int
    genesis_linked: bool
    corrupt_tail: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class DurableAuditChain:
    """File-backed, fsync'd, lock-serialized append-only hash chain."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.touch(exist_ok=True)
        # Optional fault injection for the audit-append-failure proof. When set,
        # append raises BEFORE writing — so the boundary denies before side effect.
        self._fail = False

    @property
    def path(self) -> Path:
        return self._path

    def set_fail(self, value: bool) -> None:
        self._fail = value

    def _read_all_raw(self) -> list[str]:
        with self._path.open("r", encoding="utf-8") as f:
            return [ln for ln in f.read().splitlines() if ln.strip()]

    def records(self) -> list[dict[str, Any]]:
        out = []
        for ln in self._read_all_raw():
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                break  # stop at first unparsable (corrupt) line
        return out

    def _last_durable_hash(self) -> str:
        recs = self.records()
        return recs[-1]["event_hash"] if recs else GENESIS

    def append(self, event: dict[str, Any]) -> tuple[int, str]:
        """Append a record durably (fsync) under an exclusive cross-process lock.

        Raises RuntimeError if fault-injection is enabled (audit-store outage),
        so the caller denies before the side effect. The previous_hash is read
        from the durable tail under the lock, not from memory.
        """
        if self._fail:
            raise RuntimeError("durable audit store unavailable")
        # Exclusive lock for the whole read-tail + append so concurrent writers
        # serialize and cannot fork the chain.
        with self._path.open("a+", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                existing = self.records()
                seq = len(existing)
                prev = existing[-1]["event_hash"] if existing else GENESIS
                body = dict(event)
                body["sequence"] = seq
                body["previous_hash"] = prev
                body["event_hash"] = _hash(prev, body)
                f.write(json.dumps(body, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        # fsync the directory entry so the appended line survives a crash.
        dir_fd = os.open(str(self._path.parent), os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return seq, body["event_hash"]

    def verify(self) -> VerifyResult:
        """Replay-verify the durable chain from disk. Fail-closed on corruption.

        A line that does not parse, a broken previous_hash link, or a mismatched
        event_hash makes the chain INVALID with corrupt_tail=True (so the boundary
        denies). This re-reads from disk, so it doubles as restart-replay.
        """
        raw = self._read_all_raw()
        prev = GENESIS
        count = 0
        genesis_linked = True
        for idx, ln in enumerate(raw):
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                return VerifyResult(
                    False, count, genesis_linked, True, f"unparsable record at line {idx}"
                )
            if idx == 0 and rec.get("previous_hash") != GENESIS:
                genesis_linked = False
            if rec.get("previous_hash") != prev:
                return VerifyResult(
                    False, count, genesis_linked, True, f"broken chain link at sequence {idx}"
                )
            if _hash(prev, rec) != rec.get("event_hash"):
                return VerifyResult(
                    False, count, genesis_linked, True, f"event_hash mismatch at sequence {idx}"
                )
            prev = rec["event_hash"]
            count += 1
        return VerifyResult(True, count, genesis_linked, False, "chain intact")


def reopen(path: str | os.PathLike[str]) -> DurableAuditChain:
    """Re-open a chain from disk (simulates a process restart for replay proof)."""
    return DurableAuditChain(path)
