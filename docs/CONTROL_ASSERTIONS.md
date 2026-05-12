# Syndicate Claw Control Assertions

Syndicate Claw is a governed workflow and tool execution plane. Claims here are
scoped to deployed Claw runtime paths and configured authority integrations.

| Assertion | Classification | Deployment Scope | Verification Authority | Enforcement Mode | Integrity Level | Limitations |
| --- | --- | --- | --- | --- | --- | --- |
| `syndicateclaw:tool-policy-gate:v1` | A2 | Standalone and Enterprise runtime capability | enterprise_operator | FAIL_CLOSED | observational | Tool execution requires policy evaluation and decision records before execution; this does not govern tools invoked outside Claw or deployments that disable required policy dependencies. |
| `syndicateclaw:approval-checkpoint:v1` | A2 | Runtime approval boundary | enterprise_operator | ENFORCED | observational | Approval checkpoints block configured actions until authorized, rejected, expired, or failed; Gate correlation requires configured Gate/Claw integration and does not cover provider paths outside Gate. |
| `syndicateclaw:audit-and-replay-evidence:v1` | B1 | Operator-visible runtime evidence | enterprise_operator | OBSERVABLE_ONLY | observational / GI-2 where hash or signature verification is configured | Append-only audit records and checkpoint signatures support reconstruction and replay control; they are not immutable storage, remote anchoring, GI-1 signed governance evidence, or complete evidence continuity unless explicitly implemented and verified. |

## Boundary Notes

Evidence continuity and evidence reconstruction are distinct. Recovery should
preserve discontinuities rather than rewriting or silently repairing Claw audit
or replay artifacts.
