"""Locust load scenarios for API baseline (v1.4.0).

Run: locust -f tests/perf/locustfile.py --host http://localhost:8000
"""

from __future__ import annotations

from locust import HttpUser, between, task


class SyndicateClawUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def health(self) -> None:
        self.client.get("/healthz")

    @task(1)
    def list_workflows(self) -> None:
        self.client.get("/api/v1/workflows/", headers={"X-API-Key": "sc-dev-key-001"})
