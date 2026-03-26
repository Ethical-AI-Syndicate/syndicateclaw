"""Locust load test for SyndicateClaw perf environment."""

import random
from locust import HttpUser, task, between


class SyndicateClawUser(HttpUser):
    wait_time = between(0.5, 2.0)
    token = None

    def on_start(self):
        """Authenticate before load testing."""
        resp = self.client.post("/api/v1/auth/token", json={
            "username": "perf-test",
            "password": "perf-test",
        })
        if resp.status_code == 200:
            self.token = resp.json().get("access_token")

    @task(5)
    def health_check(self):
        self.client.get("/healthz")

    @task(3)
    def list_workflows(self):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self.client.get("/api/v1/workflows", headers=headers)

    @task(2)
    def get_app_info(self):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        self.client.get("/api/v1/info", headers=headers)

    @task(1)
    def create_and_run_workflow(self):
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        wf_id = f"perf-test-{random.randint(1000, 9999)}"
        self.client.post("/api/v1/workflows", json={
            "name": wf_id,
            "description": "Load test workflow",
            "nodes": [
                {"id": "start", "type": "START", "handler": "start"},
                {"id": "end", "type": "END", "handler": "end"},
            ],
            "edges": [
                {"from_node_id": "start", "to_node_id": "end"}
            ]
        }, headers=headers)
