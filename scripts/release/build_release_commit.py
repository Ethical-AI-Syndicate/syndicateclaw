#!/usr/bin/env python3
"""Build the release commit for the signed-release flow: bump version + changelog.

In the signed-release flow (SDD-GOV-SIGNTAG-001, Option B) the annotated signed
tag must point to a **release commit** that contains the version bump and the
changelog entry — not the pre-release commit. This script creates that commit so
the subsequent ``create_signed_tag.py`` tags release state, and the provenance
manifest (generated at HEAD) binds to the same commit the tag targets.

It is deterministic and does not depend on `semantic-release` stdout: the version
is supplied (computed upstream by `semantic-release --dry-run`) and the changelog
entry is built from the conventional-commit subjects since the previous tag.

NOTE ON SCOPE: the changelog body here is a bounded summary of commit subjects,
not the full `@semantic-release/release-notes-generator` output. Actual
semantic-release release-state is therefore *not* claimed closed by this script;
it wires and proves the **invariants** (version bump + changelog present in the
tagged commit). See docs/release/SIGNED_RELEASE_FLOW.md.

Fails closed: empty version, or a commit that would carry no version/changelog
change, is an error.

Run ``--selftest`` to exercise the pure version/changelog functions without git.
"""

import argparse
import re
import subprocess
import sys
from datetime import date as _date
from pathlib import Path

_VERSION_LINE = re.compile(r'(?m)^version\s*=\s*"[^"]*"')


def bump_pyproject_version(text: str, version: str) -> str:
    """Replace the project ``version = "..."`` line. Raises if not found."""
    new, n = _VERSION_LINE.subn(f'version = "{version}"', text, count=1)
    if n != 1:
        raise ValueError("could not locate a project `version = \"...\"` line in pyproject.toml")
    return new


def build_changelog_entry(version: str, day: str, subjects: list[str]) -> str:
    """Render a changelog entry block for ``version`` from commit subjects."""
    lines = [f"## v{version} ({day})", ""]
    if subjects:
        lines += [f"* {s}" for s in subjects]
    else:
        lines.append("* (no conventional-commit subjects since previous release)")
    lines += ["", ""]
    return "\n".join(lines)


def prepend_changelog(text: str, entry: str) -> str:
    return entry + text


def run(cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def previous_tag(repo_path: Path) -> str | None:
    r = run(["git", "tag", "--sort=-creatordate"], cwd=repo_path, check=False)
    tags = [t for t in (r.stdout or "").splitlines() if t.strip()]
    return tags[0] if tags else None


def commit_subjects(repo_path: Path, since_tag: str | None) -> list[str]:
    rng = f"{since_tag}..HEAD" if since_tag else "HEAD"
    r = run(["git", "log", rng, "--format=%s"], cwd=repo_path, check=False)
    return [s for s in (r.stdout or "").splitlines() if s.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="Release version (no leading v), e.g. 2.3.0.")
    ap.add_argument("--repo-path", type=Path, default=Path("."))
    ap.add_argument("--date", default=_date.today().isoformat())
    ap.add_argument("--no-commit", action="store_true",
                    help="Mutate files but do not create the git commit.")
    ap.add_argument("--committer-name", default="syndicateclaw release")
    ap.add_argument("--committer-email", default="release-ci@syndicateclaw.local")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    if not args.version:
        print("ERROR: --version is required (fail closed).", file=sys.stderr)
        return 2

    repo = args.repo_path.resolve()
    pyproject = repo / "pyproject.toml"
    changelog = repo / "CHANGELOG.md"
    if not pyproject.exists():
        print(f"ERROR: {pyproject} missing.", file=sys.stderr)
        return 2

    # Version bump.
    try:
        new_pyproject = bump_pyproject_version(pyproject.read_text(encoding="utf-8"), args.version)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    pyproject.write_text(new_pyproject, encoding="utf-8")

    # Changelog entry.
    subs = commit_subjects(repo, previous_tag(repo))
    entry = build_changelog_entry(args.version, args.date, subs)
    existing = changelog.read_text(encoding="utf-8") if changelog.exists() else ""
    changelog.write_text(prepend_changelog(existing, entry), encoding="utf-8")

    # Fail closed: there must be a real change to commit.
    diff = run(["git", "status", "--porcelain", "pyproject.toml", "CHANGELOG.md"],
               cwd=repo, check=False).stdout.strip()
    if not diff:
        print("ERROR: no version/changelog change produced (fail closed).", file=sys.stderr)
        return 1

    print(f"Release state prepared: pyproject version=v{args.version}, "
          f"changelog entry prepended ({len(subs)} commit subject(s)).")

    if args.no_commit:
        print("NOTE: --no-commit set; release commit not created.")
        return 0

    run(["git", "add", "pyproject.toml", "CHANGELOG.md"], cwd=repo)
    # The release COMMIT is intentionally unsigned and the identity is set
    # explicitly: the signed TAG (create_signed_tag.py) is the provenance anchor,
    # and commit creation must not depend on ambient git config (a clean CI
    # runner has no committer identity, and an ambient commit.gpgsign=true would
    # otherwise force commit signing against an unavailable key).
    run(["git",
         "-c", f"user.name={args.committer_name}",
         "-c", f"user.email={args.committer_email}",
         "-c", "commit.gpgsign=false",
         "commit", "-m", f"chore(release): v{args.version} [skip ci]"], cwd=repo)
    head = run(["git", "rev-parse", "HEAD"], cwd=repo).stdout.strip()
    print(f"Created release commit {head} (chore(release): v{args.version}).")
    return 0


def _selftest() -> int:
    ok = True

    def check(desc, cond):
        nonlocal ok
        ok = ok and cond
        print(f"  [{'PASS' if cond else 'FAIL'}] {desc}")

    src = '[project]\nname = "x"\nversion = "2.2.4"\nrequires-python = ">=3.12"\n'
    bumped = bump_pyproject_version(src, "2.3.0")
    check("version line bumped", 'version = "2.3.0"' in bumped)
    check("other lines untouched", 'requires-python = ">=3.12"' in bumped)
    check("only one version line changed", bumped.count('version = "') == 1)
    try:
        bump_pyproject_version('name = "x"\n', "1.0.0")
        check("missing version raises", False)
    except ValueError:
        check("missing version raises", True)

    entry = build_changelog_entry("2.3.0", "2026-06-23", ["fix: a", "feat: b"])
    check("changelog has version header", entry.startswith("## v2.3.0 (2026-06-23)"))
    check("changelog lists subjects", "* fix: a" in entry and "* feat: b" in entry)
    empty = build_changelog_entry("2.3.0", "2026-06-23", [])
    check("empty changelog has placeholder", "no conventional-commit subjects" in empty)
    check("prepend keeps existing", prepend_changelog("OLD", entry).endswith("OLD"))

    print("SELFTEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
