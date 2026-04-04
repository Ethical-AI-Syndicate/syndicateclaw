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

## Disclosure Timeline

- 0-48 hours: Acknowledgment
- 5 business days: Initial assessment
- 30 days: Fix or mitigation deployed
- 90 days: Public disclosure (coordinated)
