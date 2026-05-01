# Multi-Environment Examples

These Kustomize overlays are sanitized examples. The base manifest already uses
`secretKeyRef` for database, Redis, and application secret values. Staging and
production overlays add sample ingress hostnames, stronger resource profiles,
and explicit observability/auth toggles. Replace image names, hostnames, and
secret names through customer deployment automation.
