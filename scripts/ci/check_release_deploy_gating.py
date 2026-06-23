#!/usr/bin/env python3
"""Release/deploy gating policy check for syndicateclaw CI.

Asserts that no release-cutting or deploy job can run AUTOMATICALLY on an
ordinary ``main`` push. "Ordinary main push" means:

    CI_PIPELINE_SOURCE == "push" and CI_COMMIT_BRANCH == "main"
    (no tag, no RELEASE/DEPLOY_* opt-in variables, not a web/operator pipeline)

Policy (fail-closed):
  * release / tag-creating jobs must NOT auto-run on an ordinary main push
    (they must require an explicit release context or be manual).
  * deploy_staging must NOT auto-run on an ordinary main push.
  * deploy_production (if present) must NOT auto-run on an ordinary main push.
  * any deploy job must be manual, tag-gated, or explicit-variable gated.

This check parses .gitlab-ci.yml and evaluates each job's first matching rule
under the ordinary-main-push environment. It NEVER runs a release or a deploy;
it only inspects rules. Run ``--selftest`` for the negative/positive unit cases.
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

# Reserved top-level keys that are not jobs.
RESERVED = {
    "stages", "workflow", "variables", "default", "include", "image",
    "services", "cache", "before_script", "after_script", "pages",
}

ORDINARY_MAIN_PUSH = {
    "CI_PIPELINE_SOURCE": "push",
    "CI_COMMIT_BRANCH": "main",
    "CI_COMMIT_TAG": "",
    "CI_DEFAULT_BRANCH": "main",
    # explicit opt-ins are intentionally UNSET for an ordinary push
    "RELEASE": "",
    "DEPLOY_STAGING": "",
    "DEPLOY_PRODUCTION": "",
}

_VAR = re.compile(r"\$\{?(\w+)\}?")


def _subst(token: str, env: dict) -> str:
    return _VAR.sub(lambda m: env.get(m.group(1), ""), token).strip()


def _eval_atom(atom: str, env: dict) -> bool:
    atom = atom.strip().strip("()").strip()
    if not atom:
        return True
    # regex match:  $VAR =~ /pattern/   or  !~
    m = re.match(r"(.+?)\s*(=~|!~)\s*/(.*)/\s*$", atom)
    if m:
        lhs = _subst(m.group(1), env)
        pat = m.group(3)
        hit = re.search(pat, lhs) is not None
        return hit if m.group(2) == "=~" else not hit
    # equality / inequality:  $VAR == "x"   /  $VAR != "x"
    m = re.match(r'(.+?)\s*(==|!=)\s*(.+)$', atom)
    if m:
        lhs = _subst(m.group(1), env)
        rhs = _subst(m.group(3).strip().strip('"').strip("'"), env)
        return (lhs == rhs) if m.group(2) == "==" else (lhs != rhs)
    # bare presence:  $VAR   (truthy if non-empty)
    return bool(_subst(atom, env))


def eval_if(expr, env: dict) -> bool:
    """Evaluate a GitLab rules `if:` expression under env. None => matches."""
    if expr is None:
        return True
    expr = str(expr).strip()
    # OR has lowest precedence, then AND. (Parens not used in these rules.)
    for or_part in re.split(r"\s*\|\|\s*", expr):
        if all(_eval_atom(a, env) for a in re.split(r"\s*&&\s*", or_part)):
            return True
    return False


def first_matching_when(rules, env: dict):
    """Return the `when` of the first matching rule, or None if no rule matches.

    GitLab default `when` for a matching rule is `on_success`.
    """
    if rules is None:
        # No rules: legacy default is on_success (runs).
        return "on_success"
    for rule in rules:
        if isinstance(rule, str):  # e.g. anchored mapping unlikely; skip
            continue
        if not isinstance(rule, dict):
            continue
        if eval_if(rule.get("if"), env):
            return rule.get("when", "on_success")
    return None  # no rule matched => job does not run


def runs_automatically(rules, env: dict) -> bool:
    when = first_matching_when(rules, env)
    return when in ("on_success", "always", "delayed")


def _job_script_text(job: dict) -> str:
    parts = []
    for k in ("script", "before_script", "after_script"):
        v = job.get(k)
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif isinstance(v, str):
            parts.append(v)
    return "\n".join(parts).lower()


def classify(name: str, job: dict):
    txt = _job_script_text(job)
    is_tag_creator = any(
        s in txt for s in ("semantic-release", "git tag", "goreleaser")
    )
    is_deploy = (
        name.startswith("deploy")
        or "kubectl" in txt
        or "helm upgrade" in txt
        or bool(job.get("environment"))
    )
    return is_tag_creator, is_deploy


# Tokens that prove the release job is wired to the signed-release flow.
# Each tuple is (human-readable requirement, list-of-acceptable-substrings); the
# job's script must contain at least one substring from each requirement.
RELEASE_SIGNING_REQUIREMENTS = [
    ("fail-closed signing-key guard", ["gpg_private_key"]),
    ("signed annotated tag creation", ["create_signed_tag", "git tag -s"]),
    ("signed provenance verification", ["--require-signed"]),
]


def check_release_signing(jobs: dict):
    """Assert the `release` job is wired to create *signed* tags, fail-closed.

    This is policy, not execution: it only inspects the job's script text. If no
    job named ``release`` exists, there is nothing to assert.
    """
    violations = []
    job = jobs.get("release")
    if not isinstance(job, dict):
        return violations
    txt = _job_script_text(job)
    for requirement, tokens in RELEASE_SIGNING_REQUIREMENTS:
        if not any(tok in txt for tok in tokens):
            violations.append(
                f"release: missing {requirement} "
                f"(expected one of: {', '.join(tokens)}). A release must be "
                f"signed and verified, or it must not happen."
            )
    return violations


def check(path: Path):
    data = yaml.safe_load(path.read_text())
    violations = []
    jobs = {
        k: v for k, v in data.items()
        if k not in RESERVED and isinstance(v, dict) and (
            "script" in v or "rules" in v or "extends" in v or "trigger" in v
        )
    }
    for name, job in jobs.items():
        tag_creator, deploy = classify(name, job)
        if not (tag_creator or deploy):
            continue
        rules = job.get("rules")
        if runs_automatically(rules, ORDINARY_MAIN_PUSH):
            kind = "tag-creating/release" if tag_creator else "deploy"
            violations.append(
                f"{name}: {kind} job auto-runs on an ordinary main push "
                f"(first matching rule under push+main is non-manual). "
                f"Require explicit release/deploy context or `when: manual`."
            )
    violations.extend(check_release_signing(jobs))
    return violations, sorted(jobs)


def selftest() -> int:
    """Negative + positive cases for the rule evaluator."""
    bad_auto_main = [{"if": '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH == "main"',
                      "when": "on_success"}]
    bad_unconditional = None  # no rules => on_success
    bad_branch_only = [{"if": '$CI_COMMIT_BRANCH == "main"'}]  # default on_success
    good_web_var = [{"if": '$CI_PIPELINE_SOURCE == "web" && $RELEASE == "true"',
                     "when": "on_success"}, {"when": "never"}]
    good_manual = [{"if": '$CI_COMMIT_BRANCH == "main"', "when": "manual",
                    "allow_failure": True}]
    good_tag_gated = [{"if": r'$CI_COMMIT_TAG =~ /^v\d+\.\d+\.\d+$/', "when": "on_success"}]
    env = ORDINARY_MAIN_PUSH
    cases = [
        ("old auto-main release rule", bad_auto_main, True),
        ("unconditional (no rules)", bad_unconditional, True),
        ("branch-only default on_success", bad_branch_only, True),
        ("web+RELEASE gated", good_web_var, False),
        ("manual on main", good_manual, False),
        ("tag-gated (semver)", good_tag_gated, False),
    ]
    ok = True
    for desc, rules, expect_auto in cases:
        got = runs_automatically(rules, env)
        status = "PASS" if got == expect_auto else "FAIL"
        if got != expect_auto:
            ok = False
        print(f"  [{status}] {desc}: auto_on_main={got} (expected {expect_auto})")

    # Release signing-config cases.
    signed_release = {"release": {"script": [
        'if [ -z "${GPG_PRIVATE_KEY:-}" ]; then exit 1; fi',
        "python3 scripts/release/create_signed_tag.py --tag v$V",
        "verify_release_provenance.py --require-signed",
    ]}}
    unsigned_release = {"release": {"script": ["npx --no-install semantic-release"]}}
    no_release = {"validate": {"script": ["ruff check"]}}
    signing_cases = [
        ("signed release job has all signing requirements", signed_release, 0),
        ("unsigned release job flagged", unsigned_release, 3),
        ("no release job => nothing to assert", no_release, 0),
    ]
    for desc, jobs, expect_n in signing_cases:
        got_n = len(check_release_signing(jobs))
        status = "PASS" if got_n == expect_n else "FAIL"
        if got_n != expect_n:
            ok = False
        print(f"  [{status}] {desc}: violations={got_n} (expected {expect_n})")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, default=Path(".gitlab-ci.yml"))
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        rc = selftest()
        print("SELFTEST:", "PASS" if rc == 0 else "FAIL")
        return rc
    violations, jobs = check(args.file)
    print(f"Inspected release/deploy-relevant jobs in {args.file} "
          f"(total jobs scanned: {len(jobs)})")
    if violations:
        print("RELEASE/DEPLOY GATING: FAIL")
        for v in violations:
            print("  - " + v)
        return 1
    print("RELEASE/DEPLOY GATING: PASS "
          "(no release/deploy job auto-runs on an ordinary main push)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
