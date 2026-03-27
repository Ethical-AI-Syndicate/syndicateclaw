# API permission table

Authoritative route permissions live in `src/syndicateclaw/authz/route_registry.py` (`ROUTE_PERMISSION_MAP` and `ROUTE_REGISTRY`).

This document is a human-readable index; when in doubt, follow the registry in source control.

- Public routes: `PUBLIC_ROUTES` in `route_registry.py` (e.g. `/healthz`, `/readyz`, `/api/v1/info`, `/builder/*`).
- Streaming SSE: exempt from RBAC; token validated in handler.
- Builder workflow saves: `workflow:manage` for API access; `BuilderCSRFMiddleware` additionally requires `X-Builder-Token` on `PUT /api/v1/workflows/{id}` when enabled.

Regenerate or extend this file when adding routes; keep descriptions aligned with OpenAPI `summary`/`description` on each endpoint.
