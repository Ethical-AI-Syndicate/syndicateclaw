# Coverage Delta

**Latest run (2026-03-31):** `pytest -m "not integration and not pentest and not chaos and not perf" --cov=src/syndicateclaw` with branch=true. Unit tests only. **Total: 80.05%** (1352 passed).

Percentages are **combined statement+branch coverage** (`branch=true`) under `src/syndicateclaw/`.

| Module (prefix) | Current % | Target % | Status |
|-----------------|-----------|----------|--------|
| `syndicateclaw.policy/` | ~93 | 85% | PASS |
| `syndicateclaw.audit/` | ~87 | 85% | PASS |
| `syndicateclaw.approval/` | ~93 | 80% | PASS |
| `syndicateclaw.authz/` | ~96 | 80% | PASS |
| `syndicateclaw.tools/` | ~82 | 80% | PASS |
| `syndicateclaw.memory/` | ~84 | 75% | PASS |
| `syndicateclaw.inference/` | ~80+ | 80% | PASS |
| **Total `syndicateclaw`** | **80.05** | 80% | **PASS** |

**Prior snapshots:**
- 2026-03-28 (integration-inclusive, line-only): total 83.5%; `memory/` 93.8%; `inference/` 86.6%
- Pre-Session 2 (unit-only): total ~74%; `memory/` ~53.5%; `inference/` ~75.0%
