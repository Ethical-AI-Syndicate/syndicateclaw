# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 2.0.x   | :white_check_mark: |
| 1.0.x   | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in SyndicateClaw, please report it responsibly.

**Do NOT open a public GitHub issue for security vulnerabilities.**

Instead, send an email to: security@syndicateclaw.dev

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge your report within 48 hours and provide a detailed response within 5 business days.

## Security Measures

- Fail-closed RBAC policy evaluation
- HMAC-SHA256 signed audit trail (append-only)
- SSRF protection on all outbound HTTP
- Ed25519 asymmetric signing support
- API key hashing (SHA-256) with expiration and revocation
- Bandit SAST + pip-audit in CI
- Trivy container image scanning

## Recent Audit Outcomes (2026)

The repository includes two audit artifacts:

- `AUDIT_FINDINGS.md` (completeness + coverage + governance audit)
- `FINAL_AUDIT_REPORT.md` (CI/pipeline hardening and remediation record)

Key outcomes and implemented remediations:

- Route registry coverage gaps were closed so FastAPI path templates (for agents, messages, and organizations) now map correctly to RBAC route specs.
- Security-critical code paths identified by SAST were hardened (raw SQL path removal, assert misuse replaced with structured exceptions, safer host binding defaults).
- CI security and reliability gates were tightened (`bandit`, `pip-audit`, semgrep/Trivy flows, migration checks, runtime schema gate).
- Database/test orchestration race conditions in CI were remediated (schema readiness synchronization, fixture lifecycle hardening, deterministic startup sequencing).
- Coverage targets called out in the audit were brought to passing thresholds for audit, policy, approval, authz, tools, memory, and inference modules.

See the source artifacts for full evidence trails, per-finding IDs, and session-level closure notes.

## Current Security Limitations

- API keys are validated, hashed, revocable, and can carry scope metadata, but OAuth-style per-key scopes are not yet an independent request-time authorization gate. RBAC authorization on the resolved actor remains authoritative.

## Disclosure Timeline

- 0-48 hours: Acknowledgment
- 5 business days: Initial assessment
- 30 days: Fix or mitigation deployed
- 90 days: Public disclosure (coordinated)
