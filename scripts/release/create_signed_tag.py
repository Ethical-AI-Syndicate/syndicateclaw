#!/usr/bin/env python3
"""Create and verify an annotated, GPG-signed git tag for the signed-release flow.

This is the tag-creation primitive for the syndicateclaw signed-release flow
(Option B: ``semantic-release`` computes the version; this script creates the
annotated **signed** tag). It is deliberately **push-free** — creating a tag and
pushing a tag are separate responsibilities, and only an authorized release
context (the gated ``release`` CI job) ever performs the push.

Safety properties:
  * Refuses to create a semver release tag (``vX.Y.Z``) unless
    ``--allow-release-tag`` is given, so dry-run / proof callers cannot
    accidentally mint a real release tag.
  * Never receives a passphrase via argv. Passphrase handling is delegated to
    git's configured ``gpg.program`` (a loopback-pinentry wrapper that reads a
    passphrase *file*), matching the CI signing infrastructure.
  * After creating the tag it **cryptographically verifies** it (the same
    ``git verify-tag`` GOODSIG+VALIDSIG check used by release provenance). If
    verification fails it deletes the just-created tag and exits non-zero, so an
    unverified signed tag is never left behind.
  * Never pushes. The caller pushes, and only under an authorized context.

Run ``--selftest`` to exercise the release-tag guard without needing GPG.
"""

import argparse
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_release_provenance import verify_tag_signature  # noqa: E402

# Semver release tags (vX.Y.Z) are protected: only an authorized release context
# may create them. Proof/dry-run callers use non-semver names.
RELEASE_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


def is_release_tag(tag: str) -> bool:
    return bool(RELEASE_TAG_RE.match(tag or ""))


def _key_match(expected: str | None, got: str | None) -> bool:
    """GPG key ids appear short (16) or full (40); compare by suffix, case-insensitive."""
    if not expected or not got:
        return True  # no expectation supplied => not a mismatch
    exp = expected.upper().replace(" ", "")
    g = str(got).upper().replace(" ", "")
    return exp.endswith(g) or g.endswith(exp)


def create_signed_tag(
    tag: str,
    key_id: str,
    message: str,
    repo_path: str = ".",
    gpg_program: str | None = None,
    commit: str = "HEAD",
) -> None:
    """Create an annotated GPG-signed tag. Raises CalledProcessError on failure.

    The passphrase is never passed here; it is supplied by ``gpg_program`` (a
    loopback wrapper reading a passphrase file). This keeps secrets out of argv.
    """
    cfg = ["-c", f"user.signingkey={key_id}"]
    if gpg_program:
        cfg += ["-c", f"gpg.program={gpg_program}"]
    subprocess.run(
        ["git", *cfg, "tag", "-s", "-m", message, tag, commit],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", help="Tag name to create or verify.")
    ap.add_argument("--key-id", help="GPG signing key id/fingerprint.")
    ap.add_argument("--message", default="signed release tag")
    ap.add_argument("--repo-path", default=".")
    ap.add_argument("--gpg-program", default=None,
                    help="Path to a gpg wrapper (loopback + passphrase-file). "
                         "Keeps the passphrase out of argv.")
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--expected-key-id", default=None,
                    help="If set, the tag signer must match this key id.")
    ap.add_argument("--allow-release-tag", action="store_true",
                    help="Permit creating a semver vX.Y.Z release tag. Only the "
                         "authorized release context should pass this.")
    ap.add_argument("--verify-only", action="store_true",
                    help="Verify an existing tag; do not create one.")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    if not args.tag:
        print("ERROR: --tag is required.", file=sys.stderr)
        return 2

    # Verify-only path: no creation, no key required.
    if args.verify_only:
        ok, signer = verify_tag_signature(args.tag, args.repo_path)
        if ok and _key_match(args.expected_key_id, signer):
            print(f"VERIFY: PASS | tag={args.tag} signer={signer}")
            return 0
        print(f"VERIFY: FAIL | tag={args.tag} signer={signer} "
              f"(annotated signed tag with matching signer required)",
              file=sys.stderr)
        return 1

    # Creation path.
    if not args.key_id:
        print("ERROR: --key-id is required to create a signed tag.", file=sys.stderr)
        return 2

    # Guard: never mint a real release tag unless explicitly authorized.
    if is_release_tag(args.tag) and not args.allow_release_tag:
        print(
            f"ERROR: refusing to create semver release tag {args.tag!r} without "
            f"--allow-release-tag. Proof/dry-run callers must use a non-semver "
            f"tag name; only the authorized release context may create vX.Y.Z.",
            file=sys.stderr,
        )
        return 2

    try:
        create_signed_tag(
            args.tag, args.key_id, args.message,
            repo_path=args.repo_path, gpg_program=args.gpg_program,
            commit=args.commit,
        )
    except subprocess.CalledProcessError as e:
        # gpg/git stderr here does not contain the passphrase (it is read from a
        # file by the wrapper); surface a bounded tail for debugging.
        detail = (e.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1]
        print(f"ERROR: signed tag creation failed: {detail[:200]}", file=sys.stderr)
        return 1

    # Fail closed: a created tag MUST cryptographically verify, else delete it.
    ok, signer = verify_tag_signature(args.tag, args.repo_path)
    if not (ok and _key_match(args.expected_key_id, signer)):
        subprocess.run(["git", "tag", "-d", args.tag],
                       cwd=args.repo_path, capture_output=True)
        print(
            f"ERROR: created tag {args.tag} failed signature verification "
            f"(signer={signer}); tag deleted. No unverified tag is left behind.",
            file=sys.stderr,
        )
        return 1

    print(f"CREATED+VERIFIED signed annotated tag: {args.tag} | signer={signer}")
    print("NOTE: tag was NOT pushed. Push is a separate, authorized step.")
    return 0


def _selftest() -> int:
    cases = [
        ("v1.2.3", True),
        ("v0.0.1", True),
        ("v10.20.30", True),
        ("provenance-ci-test/dryrun/abc", False),
        ("v1.2", False),            # not full semver
        ("v1.2.3-rc1", False),      # prerelease suffix -> not a bare release tag
        ("release-v1.2.3", False),
        ("1.2.3", False),           # no leading v
    ]
    ok = True
    for tag, expect in cases:
        got = is_release_tag(tag)
        status = "PASS" if got == expect else "FAIL"
        if got != expect:
            ok = False
        print(f"  [{status}] is_release_tag({tag!r})={got} (expected {expect})")
    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
