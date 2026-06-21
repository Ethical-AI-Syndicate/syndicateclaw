#!/usr/bin/env python3
"""AI Syndicate Release Provenance Verifier.

Parses release_manifest.json, validates hashes, signatures, GPG key and tags,
and enforces minimum defensible release provenance.
"""

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

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

def get_tag_info(tag_name, repo_path):
    if not tag_name or tag_name == "absent":
        return "absent", None
    try:
        subprocess.run(["git", "show-ref", "--tags", "--verify", f"refs/tags/{tag_name}"], cwd=repo_path, check=True, capture_output=True)
    except subprocess.CalledProcessError:
        return "absent", None
        
    obj_type = run_cmd(["git", "cat-file", "-t", tag_name], cwd=repo_path)
    obj_sha = run_cmd(["git", "rev-parse", f"refs/tags/{tag_name}"], cwd=repo_path)
    
    if obj_type == "commit":
        return "lightweight", obj_sha
    elif obj_type == "tag":
        content = run_cmd(["git", "cat-file", "tag", tag_name], cwd=repo_path)
        if content and "-----BEGIN PGP SIGNATURE-----" in content:
            return "annotated_signed", obj_sha
        else:
            return "annotated_unsigned", obj_sha
    return "absent", None

def get_unsigned_legacy_tags(repo_path):
    tags = run_cmd(["git", "tag"], cwd=repo_path)
    if not tags:
        return []
    unsigned = []
    for t in tags.splitlines():
        t_type, _ = get_tag_info(t, repo_path)
        if t_type != "annotated_signed":
            unsigned.append(t)
    return unsigned

def verify_gpg_signature(manifest_hash: str, signature: str, key_id: str) -> bool:
    if not signature or not key_id:
        return False
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        hash_file = tmp_path / "hash.txt"
        sig_file = tmp_path / "sig.asc"
        hash_file.write_text(manifest_hash, encoding="utf-8")
        sig_file.write_text(signature, encoding="utf-8")
        
        # Verify using gpg CLI
        try:
            subprocess.run(
                ["gpg", "--verify", str(sig_file), str(hash_file)],
                check=True, capture_output=True
            )
            return True
        except Exception:
            return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("release_manifest.json"))
    parser.add_argument("--repo-path", type=Path, default=Path("."))
    parser.add_argument("--require-signed", action="store_true")
    parser.add_argument(
        "--expected-key-id",
        type=str,
        default=os.environ.get("RELEASE_SIGNING_KEY_ID") or os.environ.get("GPG_KEY_ID"),
        help="If set (or RELEASE_SIGNING_KEY_ID/GPG_KEY_ID in env), the manifest "
        "signer key id must match this value when a signature is present.",
    )
    args = parser.parse_args()

    repo_path = args.repo_path.resolve()
    manifest_path = repo_path / args.manifest

    verdict = {
        "status": "fail",
        "repo": repo_path.name,
        "commit": None,
        "tag": None,
        "signed_tag_verified": False,
        "manifest_signature_verified": False,
        "signer_key_id": None,
        "signature_algorithm": None,
        "unsigned_legacy_tags": [],
        "errors": [],
        "warnings": [],
        "not_proven": []
    }

    if not manifest_path.exists():
        verdict["errors"].append(f"Release manifest {manifest_path} does not exist")
        verdict["not_proven"].append("release provenance")
        print(json.dumps(verdict, indent=2))
        sys.exit(1)

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        verdict["errors"].append(f"Failed to parse release manifest JSON: {e}")
        verdict["not_proven"].append("release provenance")
        print(json.dumps(verdict, indent=2))
        sys.exit(1)

    verdict["repo"] = manifest.get("repo", repo_path.name)
    verdict["commit"] = manifest.get("commit_sha")
    verdict["tag"] = manifest.get("tag")

    # 1. Recompute and verify manifest hash
    orig_hash = manifest.get("manifest_hash")
    orig_sig = manifest.get("signature")
    orig_key_id = manifest.get("signer_key_id")
    orig_algo = manifest.get("signature_algorithm")
    orig_status = manifest.get("verification_status")
    verdict["signer_key_id"] = orig_key_id
    verdict["signature_algorithm"] = orig_algo
    
    # Exclude mutable verification fields to check hash determinism
    calc_manifest = manifest.copy()
    calc_manifest["manifest_hash"] = None
    calc_manifest["signature"] = None
    calc_manifest["signer_key_id"] = None
    calc_manifest["signature_algorithm"] = None
    calc_manifest["verification_status"] = "unsigned"
    
    calc_string = json.dumps(calc_manifest, sort_keys=True)
    calc_hash = hashlib.sha256(calc_string.encode("utf-8")).hexdigest()

    if calc_hash != orig_hash:
        verdict["errors"].append(f"Manifest hash mismatch! Recomputed: {calc_hash}, Manifest recorded: {orig_hash}")

    # 2. Verify GPG signature if present
    if orig_sig:
        # Only the GPG algorithm is supported by this verifier contract.
        if orig_algo != "gpg":
            verdict["errors"].append(
                f"Unsupported signature_algorithm {orig_algo!r}; expected 'gpg'"
            )
        sig_ok = verify_gpg_signature(calc_hash, orig_sig, orig_key_id)
        if sig_ok:
            verdict["manifest_signature_verified"] = True
        else:
            verdict["errors"].append(f"GPG signature verification failed for key {orig_key_id}")
        # If an expected signer key id is supplied, the manifest must match it.
        # GPG key ids appear in short (16-char) or full (40-char fingerprint)
        # forms, so compare by suffix, case-insensitively.
        if args.expected_key_id and orig_key_id:
            exp = args.expected_key_id.upper().replace(" ", "")
            got = str(orig_key_id).upper().replace(" ", "")
            if not (exp.endswith(got) or got.endswith(exp)):
                verdict["errors"].append(
                    f"Signer key id {orig_key_id} does not match expected key id"
                )
    else:
        if args.require_signed or orig_status == "signed":
            verdict["errors"].append("Signed provenance required but no signature found in manifest")
        verdict["not_proven"].append("signed manifest")

    # 3. Check tag type against live git repo
    actual_tag_type, actual_tag_sha = get_tag_info(manifest.get("tag"), repo_path)
    expected_tag_type = manifest.get("tag_type")

    if actual_tag_type != expected_tag_type:
        verdict["errors"].append(f"Tag type mismatch! Recorded: {expected_tag_type}, Actual: {actual_tag_type}")

    if actual_tag_type == "annotated_signed":
        verdict["signed_tag_verified"] = True
    else:
        if args.require_signed:
            verdict["errors"].append(f"Signed annotated tag required but found tag type: {actual_tag_type}")
        verdict["not_proven"].append("signed tag")

    # 4. Check artifact hashes
    for art, recorded_hash in manifest.get("artifact_hashes", {}).items():
        art_path = repo_path / art
        if not art_path.exists():
            verdict["errors"].append(f"Declared artifact {art} missing from disk")
        else:
            actual_hash = sha256_file(art_path)
            if actual_hash != recorded_hash:
                verdict["errors"].append(f"Artifact {art} hash mismatch! Live: {actual_hash}, Manifest: {recorded_hash}")

    # 5. Check dependency lockfile hashes
    for lock, recorded_hash in manifest.get("dependency_lock_hashes", {}).items():
        lock_path = repo_path / lock
        if not lock_path.exists():
            verdict["errors"].append(f"Lockfile {lock} missing from disk but declared in manifest")
        else:
            actual_hash = sha256_file(lock_path)
            if actual_hash != recorded_hash:
                verdict["errors"].append(f"Lockfile {lock} hash mismatch! Live: {actual_hash}, Manifest: {recorded_hash}")

    # 6. Inventory legacy unsigned tags
    verdict["unsigned_legacy_tags"] = get_unsigned_legacy_tags(repo_path)

    # 7. Check for null-signature in RELEASE-BOUND attestations across the repo.
    #    Broadened beyond docs/evidence/** so a release-bound attestation cannot
    #    hide in another directory. Detection is strict: only artifacts that bind
    #    themselves to a specific release (manifest shape, a version-like tag/release
    #    field, or a release-typed artifact) are evaluated. Advisory/runtime evidence,
    #    JSON Schemas, fixtures/examples, and the manifest itself are excluded, so the
    #    scan does not false-positive on documentation-governance records that are
    #    legitimately observable-only or self-declared non-release.
    skip_dirs = {".git", ".worktrees", "node_modules", ".venv", "venv",
                 "examples", "test", "tests", "testdata", "fixtures",
                 "vendor", "templates", "__pycache__", "dist", "build"}
    manifest_name = manifest_path.name

    def _release_bound(data):
        if not isinstance(data, dict):
            return False
        # Explicit opt-outs: advisory / observable-only / self-declared non-release.
        if data.get("release_bound") is False:
            return False
        if str(data.get("enforcement_mode", "")).upper() == "OBSERVABLE_ONLY":
            return False
        if data.get("release_bound") is True:
            return True
        # Release-manifest shape.
        if {"commit_sha", "tag", "manifest_hash"}.issubset(data.keys()):
            return True
        # Explicit release/tag reference with a version-like value.
        for key in ("tag", "release_tag", "release", "release_ref"):
            val = data.get(key)
            if isinstance(val, str) and (val[:1] == "v" or val[:1].isdigit()):
                return True
        for key in ("artifact_type", "type", "event_class"):
            val = data.get(key)
            if isinstance(val, str) and "release" in val.lower():
                return True
        return False

    def _effective_signature(data):
        # Returns (has_signature_field, value); supports nested integrity.signature.
        if isinstance(data, dict):
            if "signature" in data:
                return True, data.get("signature")
            integ = data.get("integrity")
            if isinstance(integ, dict) and "signature" in integ:
                return True, integ.get("signature")
        return False, None

    for root, sub_dirs, files in os.walk(repo_path):
        sub_dirs[:] = [d for d in sub_dirs if d not in skip_dirs]
        for fn in files:
            if not fn.endswith(".json"):
                continue
            if fn.endswith(".schema.json") or fn == manifest_name or fn == "release_manifest.json":
                continue
            low = fn.lower()
            if any(tok in low for tok in ("placeholder", "template", "sample", "fixture", "example")):
                continue
            fpath = Path(root) / fn
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not _release_bound(data):
                continue
            has_sig, sig = _effective_signature(data)
            rel = fpath.relative_to(repo_path)
            if not has_sig or sig is None or sig == "":
                verdict["errors"].append(f"Release-bound attestation {rel} has null/missing signature")

    # Determine status
    if not verdict["errors"]:
        verdict["status"] = "pass"
    else:
        verdict["status"] = "fail"

    # Print result to stdout
    print(json.dumps(verdict, indent=2))
    
    if verdict["status"] == "fail":
        sys.exit(1)
    sys.exit(0)

if __name__ == "__main__":
    main()
