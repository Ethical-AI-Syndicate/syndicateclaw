#!/usr/bin/env python3
"""AI Syndicate Release Manifest Generator.

Collects repository metadata, dependency lockfiles, artifacts, GPG signature,
and test evidence to produce a standardized release_manifest.json.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, UTC
from pathlib import Path

SCHEMA_VERSION = "1.0.0"

def run_cmd(cmd, cwd=None):
    try:
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return None

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def get_tag_info(tag_name):
    if not tag_name:
        return "absent", None
    try:
        subprocess.run(["git", "show-ref", "--tags", "--verify", f"refs/tags/{tag_name}"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        return "absent", None
        
    obj_type = run_cmd(["git", "cat-file", "-t", tag_name])
    obj_sha = run_cmd(["git", "rev-parse", f"refs/tags/{tag_name}"])
    
    if obj_type == "commit":
        return "lightweight", obj_sha
    elif obj_type == "tag":
        content = run_cmd(["git", "cat-file", "tag", tag_name])
        if content and "-----BEGIN PGP SIGNATURE-----" in content:
            return "annotated_signed", obj_sha
        else:
            return "annotated_unsigned", obj_sha
    return "absent", None

def get_lockfile_hashes(repo_path: Path) -> dict[str, str]:
    lockfile_names = [
        "go.sum",
        "uv.lock",
        "poetry.lock",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "Cargo.lock"
    ]
    hashes = {}
    for name in lockfile_names:
        p = repo_path / name
        if p.exists():
            hashes[name] = sha256_file(p)
    return hashes

def get_test_evidence(repo_path: Path) -> dict[str, str]:
    evidence = {}
    evidence_paths = [
        "coverage.xml",
        "junit.xml",
        "integration-junit.xml",
        "claw-golden-path-junit.xml",
        "bandit_report.json",
        "audit_report.json",
        "semgrep_report.json"
    ]
    for name in evidence_paths:
        p = repo_path / name
        if p.exists():
            evidence[name] = sha256_file(p)
        for sub in ["tests", "target", "build", "artifacts"]:
            p_sub = repo_path / sub / name
            if p_sub.exists():
                evidence[f"{sub}/{name}"] = sha256_file(p_sub)
    return evidence

def get_previous_release(tag_name: str) -> str | None:
    if not tag_name:
        return None
    tags = run_cmd(["git", "tag", "--sort=-creatordate"])
    if tags:
        tag_list = tags.splitlines()
        try:
            idx = tag_list.index(tag_name)
            if idx + 1 < len(tag_list):
                return tag_list[idx + 1]
        except ValueError:
            pass
    return None

def detect_gpg_key() -> str | None:
    # Explicit env override (release tooling: RELEASE_SIGNING_KEY_ID; CI custody: GPG_KEY_ID).
    for env_name in ("RELEASE_SIGNING_KEY_ID", "GPG_KEY_ID"):
        val = os.environ.get(env_name)
        if val:
            return val
    keys = run_cmd(["gpg", "--list-secret-keys", "--with-colons"])
    if keys:
        for line in keys.splitlines():
            parts = line.split(":")
            if parts[0] == "sec":
                return parts[4]
    return None

def _detect_passphrase() -> str | None:
    # RELEASE_SIGNING_PASSPHRASE preferred; GPG_PASSPHRASE is the CI custody variable.
    return os.environ.get("RELEASE_SIGNING_PASSPHRASE") or os.environ.get("GPG_PASSPHRASE")

def sign_hash(manifest_hash: str, key_id: str) -> tuple[str | None, str | None]:
    """Produce a detached, ASCII-armored GPG signature over ``manifest_hash``.

    Supports passphrase-protected keys non-interactively via loopback pinentry.
    The passphrase is passed on a dedicated file descriptor (never via argv) so
    it cannot appear in process listings or logs. The data to sign is fed on
    stdin. Neither the passphrase nor any key material is logged.
    """
    if not key_id:
        return None, None
    base = [
        "gpg", "--local-user", key_id,
        "--detach-sign", "--armor",
        "--batch", "--yes", "--no-tty",
        "--pinentry-mode", "loopback",
    ]
    passphrase = _detect_passphrase()
    try:
        if passphrase:
            # Passphrase travels on a private pipe fd, not argv.
            read_fd, write_fd = os.pipe()
            try:
                os.write(write_fd, (passphrase + "\n").encode("utf-8"))
            finally:
                os.close(write_fd)
            try:
                p = subprocess.run(
                    base + ["--passphrase-fd", str(read_fd)],
                    input=manifest_hash.encode("utf-8"),
                    capture_output=True,
                    check=True,
                    pass_fds=(read_fd,),
                )
            finally:
                os.close(read_fd)
        else:
            p = subprocess.run(
                base,
                input=manifest_hash.encode("utf-8"),
                capture_output=True,
                check=True,
            )
        signature = p.stdout.decode("utf-8").strip()
        if not signature:
            return None, None
        return signature, "gpg"
    except subprocess.CalledProcessError as e:
        # gpg stderr never contains the passphrase or key material; surface a
        # bounded tail to aid debugging without leaking secrets.
        detail = (e.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1]
        print(f"Warning: GPG signing failed ({detail[:200]}).", file=sys.stderr)
        return None, None
    except Exception:
        print("Warning: GPG signing failed (key/passphrase unavailable).", file=sys.stderr)
        return None, None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-path", type=Path, default=Path("."))
    parser.add_argument("--repo-name", type=str)
    parser.add_argument("--tag", type=str)
    parser.add_argument("--artifacts", nargs="*", default=[])
    parser.add_argument("--key-id", type=str)
    parser.add_argument("--out", type=Path, default=Path("release_manifest.json"))
    parser.add_argument(
        "--require-signing",
        action="store_true",
        help="Exit non-zero if a signature is not produced (for signed dry-runs). "
        "Without this flag, signing failure falls back to an unsigned manifest.",
    )
    args = parser.parse_args()

    repo_path = args.repo_path.resolve()
    repo_name = args.repo_name or repo_path.name

    commit_sha = run_cmd(["git", "rev-parse", "HEAD"], cwd=repo_path)
    branch = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    
    tag = args.tag or run_cmd(["git", "describe", "--tags", "--exact-match"], cwd=repo_path)
    tag_type, tag_object_sha = get_tag_info(tag)

    previous_release = get_previous_release(tag)
    lockfiles = get_lockfile_hashes(repo_path)
    test_evidence = get_test_evidence(repo_path)

    artifact_hashes = {}
    for art in args.artifacts:
        art_path = repo_path / art
        if art_path.exists():
            artifact_hashes[art] = sha256_file(art_path)
        else:
            artifact_hashes[art] = "none"

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "repo": repo_name,
        "commit_sha": commit_sha,
        "branch": branch,
        "tag": tag or "absent",
        "tag_object_sha": tag_object_sha or "absent",
        "tag_type": tag_type,
        "manifest_hash": None,
        "artifact_hashes": artifact_hashes,
        "dependency_lock_hashes": lockfiles,
        "test_evidence": test_evidence,
        "ci_pipeline_id": os.environ.get("CI_PIPELINE_ID"),
        "signer_key_id": None,
        "signature_algorithm": None,
        "signature": None,
        "previous_release": previous_release or "none",
        "generated_at": datetime.now(UTC).isoformat() + "Z",
        "verification_status": "unsigned"
    }

    # Calculate manifest_hash (excluding mutable signature fields)
    manifest_string = json.dumps(manifest, sort_keys=True)
    manifest_hash = hashlib.sha256(manifest_string.encode("utf-8")).hexdigest()
    manifest["manifest_hash"] = manifest_hash

    # Signing step
    key_id = args.key_id or detect_gpg_key()
    signed = False
    if key_id:
        signature, algo = sign_hash(manifest_hash, key_id)
        if signature:
            manifest["signer_key_id"] = key_id
            manifest["signature_algorithm"] = algo
            manifest["signature"] = signature
            manifest["verification_status"] = "signed"
            signed = True
        else:
            print("Warning: Signing failed. Manifest remains unsigned.", file=sys.stderr)
    else:
        print("Note: No GPG signing key detected. Manifest remains unsigned.", file=sys.stderr)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
    print(f"Release manifest written to {args.out} (status: {manifest['verification_status']})")

    # Fail closed for signed dry-runs: an unsigned result must not pass silently.
    if args.require_signing and not signed:
        print(
            "ERROR: --require-signing was set but the manifest is unsigned "
            "(no signing key, or signing failed).",
            file=sys.stderr,
        )
        sys.exit(1)

if __name__ == "__main__":
    main()
