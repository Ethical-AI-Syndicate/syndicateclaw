# Ephemeral Review Environments

SyndicateClaw creates on-demand environments per merge request using SSH reverse tunnels + Nginx reverse proxy on a GCP ingress host.

## How It Works

```
MR opened → CI spins up:
  pr-123.syndicateclaw.mikeholownych.com
  ├── syndicateclaw-pr-123 (container on Proxmox)
  ├── postgres-pr-123 (shared Postgres, new DB)
  ├── SSH reverse tunnel (Proxmox → GCP)
  ├── Nginx config (GCP, routes hostname → tunnel port)
  └── Cloudflare DNS CNAME (DNS-only, no proxy)

MR merged/closed → CI tears down:
  → Kill tunnel → Remove Nginx config → Remove DNS → Stop container → Drop DB
```

## Flow

```
MR Event          CI Job              What Happens
───────────       ────────            ──────────────────────────
MR opened    →    build_mr()     →    Build & push image
                create_review() →    Provision env (DB, container, tunnel, DNS)

MR updated   →    build_mr()     →    Rebuild & push
                create_review() →    Replace container (same tunnel/DNS)

MR closed    →    destroy_review() →  Tear down everything
MR merged    →    destroy_review() →  Tear down everything

Manual       →    destroy_review() →  Teardown button in GitLab UI
```

## URL Pattern

```
pr-<MR_IID>.syndicateclaw.mikeholownych.com
```

Each environment gets:
- An isolated PostgreSQL database: `review_pr_<iid>`
- Its own Redis DB (5-54 reserved for review envs)
- A free port in the 8010-8099 range
- An SSH reverse tunnel to the GCP host
- A Cloudflare DNS-only CNAME record

## Required CI Variables

| Variable | Description |
|----------|-------------|
| `REGISTRY_USER` | Container registry username |
| `REGISTRY_PASSWORD` | Container registry token |
| `GCP_HOST` | GCP ingress host address |
| `GCP_USER` | SSH user on GCP (default: root) |
| `GCP_SSH_KEY` | SSH private key for GCP (set as protected/masked) |
| `CLOUDFLARE_ZONE_ID` | Cloudflare DNS zone ID |
| `CLOUDFLARE_API_TOKEN` | Cloudflare API token (DNS write scope) |
| `STAGING_SECRET_KEY` | Secret for staging environment |

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/env-provision.sh <mr-iid> <sha>` | Create review env |
| `scripts/env-teardown.sh <mr-iid>` | Destroy review env |
| `scripts/env-sweep.sh` | Clean stale envs (>24h) |

## GCP Host Requirements

The GCP host needs:

1. **Nginx** with Let's Encrypt certs for `*.syndicateclaw.mikeholownych.com`
2. **SSH access** from GitLab CI runner (via `GCP_SSH_KEY`)
3. **`GatewayPorts yes`** in sshd_config (to allow reverse tunnels)

## DNS Setup

Create a wildcard CNAME in Cloudflare (DNS-only, gray cloud):

```
*.syndicateclaw.mikeholownych.com  →  <GCP_HOST>  (A record)
```

Or individual records created dynamically by the provisioning script.

## Cleanup

Stale environments (>24h) are cleaned up via:
- GitLab scheduled pipeline (recommended: every 4 hours)
- Manual: `scripts/env-sweep.sh` or `scripts/env-sweep.sh --dry-run`
