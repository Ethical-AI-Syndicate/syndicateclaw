# Product Modes

## Standalone Mode

Standalone buyer: teams that need human-in-the-loop approval workflows, agent orchestration, policy decisions, and audit trails without adopting the full Syndicate stack.

Required dependencies:

- PostgreSQL.
- Redis.
- JWT/API-key auth configuration.
- Optional model provider config if inference execution is used.
- No Gate or ControlPlane dependency is required.

Standalone value:

- Define and run workflows.
- Create approval tasks.
- Approve or reject requests.
- Record policy and audit evidence.

## Enterprise Mode

Enterprise platform buyer: security/platform teams that want Claw to act as the approval and workflow layer in front of centralized model execution.

Optional dependencies:

- `syndicategate-enterprise` as a provider target for model execution.
- `controlplane-enterprise` for central event/tenant telemetry once the connector is implemented.
- `syndicatecode` as an initiating client once workflow intake is wired.

Enterprise behavior must remain optional. If Gate is configured but unreachable, Claw should return a clear provider/route failure and keep standalone workflow operations available.

## Upgrade Path

Deploy Claw standalone for approvals and orchestration. Add Gate by configuring a provider YAML entry pointing to the gateway. Add ControlPlane and SyndicateCode after the unified governed execution contract is wired.

## Technical Packaging Notes

Current inference policy defaults fail closed. A production enterprise profile must seed explicit rules for `inference/chat/invoke` and `model/use` before Claw can route model requests.
