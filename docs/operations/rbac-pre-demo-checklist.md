# RBAC Pre-demo Checklist

Ensure the environment is correctly seeded and invariants are passing before any demo or deployment.

## Available flags

| Flag | Behavior |
|------|----------|
| (none) | Full seed — extract actors, create principals/roles/assignments, verify |
| `--dry-run` | Print what would be created without committing. Use to preview. |
| `--verify` | Run invariant checks only. Exit 0 = seeded correctly. Exit 1 = problems found. |

## Recommended pre-demo sequence

```bash
# 1. Preview what will be seeded (no DB changes)
python scripts/seed_rbac_phase0.py --dry-run

# 2. Run the seed
python scripts/seed_rbac_phase0.py

# 3. Confirm all invariants pass
python scripts/seed_rbac_phase0.py --verify
# Must exit 0

# 4. If enforcement is ON, confirm no PRINCIPAL_NOT_FOUND in shadow evaluations
pytest tests/unit/test_rbac_shadow_gate.py -v
# All 3 tests must pass
```
