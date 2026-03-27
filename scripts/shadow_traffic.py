"""Comprehensive shadow-mode traffic generator for Phase 1 validation.

Exercises every registered protected route with both allow and deny cases,
multiple principals, ownership boundary conditions, and edge cases.
Designed to run against a staging environment with seeded Phase 0 data.
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field

import httpx

BASE_URL = "http://localhost:8002"

SECRET_KEY = "staging-secret-not-for-production"

# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------

def make_token(actor: str, scopes: list[str] | None = None) -> str:
    from syndicateclaw.security.auth import create_access_token
    from datetime import timedelta
    return create_access_token(
        actor,
        timedelta(hours=1),
        secret_key=SECRET_KEY,
    )


@dataclass
class TrafficResult:
    route: str
    method: str
    actor: str
    status: int
    note: str = ""


results: list[TrafficResult] = []


_request_count = 0

async def req(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    actor: str,
    token: str,
    body: dict | None = None,
    note: str = "",
    headers: dict | None = None,
) -> httpx.Response:
    global _request_count
    _request_count += 1
    # Pace requests to stay within burst rate limits
    if _request_count % 5 == 0:
        await asyncio.sleep(0.3)

    hdrs = {"Authorization": f"Bearer {token}"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        hdrs["Content-Type"] = "application/json"
    resp = await client.request(
        method,
        f"{BASE_URL}{path}",
        content=json.dumps(body) if body else None,
        headers=hdrs,
        timeout=15.0,
    )
    results.append(TrafficResult(
        route=path, method=method, actor=actor, status=resp.status_code, note=note,
    ))
    if resp.status_code == 429:
        await asyncio.sleep(1.0)
    return resp


async def run_traffic():
    # Tokens for different principals
    alice_token = make_token("user:alice", ["workflow:create", "memory:write"])
    bob_token = make_token("user:bob", ["workflow:create"])
    admin_token = make_token("admin:ops", ["admin:all"])
    engine_token = make_token("system:engine", [])

    async with httpx.AsyncClient() as client:
        # ==================================================================
        # WORKFLOWS (5 routes)
        # ==================================================================

        # POST /api/v1/workflows/ — alice creates (ALLOW)
        import time as _t
        _ts = str(int(_t.time() * 1000))[-6:]
        r = await req(client, "POST", "/api/v1/workflows/",
                      actor="user:alice", token=alice_token,
                      body={"name": f"traffic-wf-{_ts}", "version": "1.0.0",
                            "description": "traffic test", "nodes": [], "edges": []},
                      note="create workflow (allow)")
        new_wf_id = r.json().get("id") if r.status_code == 201 else None

        # GET /api/v1/workflows/ — alice lists (ALLOW, ownership_filter)
        await req(client, "GET", "/api/v1/workflows/",
                  actor="user:alice", token=alice_token,
                  note="list workflows owner=alice (allow)")

        # GET /api/v1/workflows/ — bob lists (ALLOW, ownership_filter)
        await req(client, "GET", "/api/v1/workflows/",
                  actor="user:bob", token=bob_token,
                  note="list workflows owner=bob (allow)")

        # GET /api/v1/workflows/{id} — alice reads own (ALLOW)
        await req(client, "GET", f"/api/v1/workflows/wf-002",
                  actor="user:alice", token=alice_token,
                  note="get own workflow (allow)")

        # GET /api/v1/workflows/{id} — bob reads alice's (ownership 404=DENY)
        await req(client, "GET", f"/api/v1/workflows/wf-002",
                  actor="user:bob", token=bob_token,
                  note="get other's workflow (deny, ownership)")

        # GET /api/v1/workflows/{id} — admin reads admin's own (ALLOW)
        await req(client, "GET", f"/api/v1/workflows/wf-001",
                  actor="admin:ops", token=admin_token,
                  note="get admin-owned workflow (allow)")

        # GET /api/v1/workflows/{id} — nonexistent ID
        await req(client, "GET", "/api/v1/workflows/nonexistent-wf",
                  actor="user:alice", token=alice_token,
                  note="get nonexistent workflow (404)")

        # ==================================================================
        # WORKFLOW RUNS (9 routes)
        # ==================================================================

        # POST /api/v1/workflows/{id}/runs — alice starts run on own workflow
        r = await req(client, "POST", f"/api/v1/workflows/wf-002/runs",
                      actor="user:alice", token=alice_token,
                      body={"initiated_by": "user:alice"},
                      note="start run on own workflow (allow)")
        new_run_id = r.json().get("id") if r.status_code in (200, 201) else None

        # POST /api/v1/workflows/{id}/runs — bob starts run on alice's workflow
        await req(client, "POST", f"/api/v1/workflows/wf-002/runs",
                  actor="user:bob", token=bob_token,
                  body={"initiated_by": "user:bob"},
                  note="start run on other's workflow (allow, no legacy ownership on create)")

        # GET /api/v1/workflows/runs — alice lists runs
        await req(client, "GET", "/api/v1/workflows/runs",
                  actor="user:alice", token=alice_token,
                  note="list runs (allow)")

        # GET /api/v1/workflows/runs — bob lists runs
        await req(client, "GET", "/api/v1/workflows/runs",
                  actor="user:bob", token=bob_token,
                  note="list runs as bob (allow)")

        # GET /api/v1/workflows/runs/{id} — alice reads own run
        await req(client, "GET", f"/api/v1/workflows/runs/run-002",
                  actor="user:alice", token=alice_token,
                  note="get own run (allow)")

        # GET /api/v1/workflows/runs/{id} — bob reads alice's run (ownership 404=DENY)
        await req(client, "GET", f"/api/v1/workflows/runs/run-002",
                  actor="user:bob", token=bob_token,
                  note="get other's run (deny, ownership)")

        # GET /api/v1/workflows/runs/{id} — bob reads own run
        await req(client, "GET", f"/api/v1/workflows/runs/run-003",
                  actor="user:bob", token=bob_token,
                  note="get own run (allow)")

        # POST pause/resume/cancel on bob's run (ownership)
        await req(client, "POST", f"/api/v1/workflows/runs/run-003/pause",
                  actor="user:bob", token=bob_token,
                  note="pause own run (allow or status error)")

        await req(client, "POST", f"/api/v1/workflows/runs/run-003/resume",
                  actor="user:bob", token=bob_token,
                  note="resume own run (allow or status error)")

        await req(client, "POST", f"/api/v1/workflows/runs/run-003/cancel",
                  actor="user:bob", token=bob_token,
                  note="cancel own run (allow or status error)")

        # POST pause on alice's run by bob (ownership deny)
        await req(client, "POST", f"/api/v1/workflows/runs/run-002/pause",
                  actor="user:bob", token=bob_token,
                  note="pause other's run (deny, ownership)")

        # POST replay on own run
        await req(client, "POST", f"/api/v1/workflows/runs/run-003/replay",
                  actor="user:bob", token=bob_token,
                  body={},
                  note="replay own run (allow or status error)")

        # POST replay on other's run (deny)
        await req(client, "POST", f"/api/v1/workflows/runs/run-002/replay",
                  actor="user:bob", token=bob_token,
                  body={},
                  note="replay other's run (deny, ownership)")

        # GET nodes for run
        await req(client, "GET", f"/api/v1/workflows/runs/run-002/nodes",
                  actor="user:alice", token=alice_token,
                  note="get run nodes (allow)")

        # GET nodes — bob on alice's run (legacy: no ownership check!)
        await req(client, "GET", f"/api/v1/workflows/runs/run-002/nodes",
                  actor="user:bob", token=bob_token,
                  note="get other's run nodes (allow, legacy gap)")

        # GET run timeline
        await req(client, "GET", f"/api/v1/workflows/runs/run-002/timeline",
                  actor="user:alice", token=alice_token,
                  note="get run timeline (allow)")

        # GET run timeline — bob on alice's run (legacy: no ownership check)
        await req(client, "GET", f"/api/v1/workflows/runs/run-002/timeline",
                  actor="user:bob", token=bob_token,
                  note="get other's run timeline (allow, legacy gap)")

        # ==================================================================
        # MEMORY (6 routes)
        # ==================================================================

        # POST /api/v1/memory/ — write (unique key per run)
        import time as _t
        _ts = str(int(_t.time() * 1000))[-6:]
        r = await req(client, "POST", "/api/v1/memory/",
                      actor="user:alice", token=alice_token,
                      body={"namespace": "traffic:ns", "key": f"test-{_ts}",
                            "value": {"data": "shadow-traffic"},
                            "memory_type": "SEMANTIC", "source": "traffic-gen"},
                      note="write memory (allow)")
        mem_id = r.json().get("id") if r.status_code == 201 else None

        # POST /api/v1/memory/ — bob writes
        r2 = await req(client, "POST", "/api/v1/memory/",
                       actor="user:bob", token=bob_token,
                       body={"namespace": "traffic:ns", "key": f"bob-{_ts}",
                             "value": {"data": "bob-data"},
                             "memory_type": "STRUCTURED", "source": "traffic-gen"},
                       note="write memory as bob (allow)")

        # GET /api/v1/memory/{namespace}/{key} — read specific
        await req(client, "GET", f"/api/v1/memory/traffic:ns/test-{_ts}",
                  actor="user:alice", token=alice_token,
                  note="read own memory (allow)")

        # GET /api/v1/memory/{namespace}/{key} — bob reads alice's private
        await req(client, "GET", f"/api/v1/memory/traffic:ns/test-{_ts}",
                  actor="user:bob", token=bob_token,
                  note="read other's private memory (deny, access_policy)")

        # GET /api/v1/memory/{namespace} — search
        await req(client, "GET", "/api/v1/memory/traffic:ns",
                  actor="user:alice", token=alice_token,
                  note="search memory namespace (allow)")

        # GET /api/v1/memory/{namespace} — search different namespace
        await req(client, "GET", "/api/v1/memory/agent:facts",
                  actor="user:alice", token=alice_token,
                  note="search namespace with private records (allow, filtered)")

        # PUT /api/v1/memory/{id} — update own (use pre-existing alice record)
        await req(client, "PUT", "/api/v1/memory/mem-002",
                  actor="user:alice", token=alice_token,
                  body={"value": {"theme": "dark-updated"}},
                  note="update own memory (allow)")
        
        # PUT /api/v1/memory/{id} — bob updates alice's (deny, access_policy)
        await req(client, "PUT", "/api/v1/memory/mem-002",
                  actor="user:bob", token=bob_token,
                  body={"value": {"theme": "intruder"}},
                  note="update other's memory (deny, access_policy)")

        # DELETE /api/v1/memory/{id} — bob deletes engine's (deny, access_policy)
        await req(client, "DELETE", "/api/v1/memory/mem-001",
                  actor="user:bob", token=bob_token,
                  note="delete other's memory (deny, access_policy)")

        # GET /api/v1/memory/{id}/lineage
        await req(client, "GET", "/api/v1/memory/mem-002/lineage",
                  actor="user:alice", token=alice_token,
                  note="get memory lineage (allow)")

        # GET /api/v1/memory/{id}/lineage — bob on alice's (deny)
        await req(client, "GET", "/api/v1/memory/mem-002/lineage",
                  actor="user:bob", token=bob_token,
                  note="get other's memory lineage (deny, access_policy)")

        # ==================================================================
        # POLICIES (6 routes)
        # ==================================================================

        # POST /api/v1/policies/ — admin (allow)
        r = await req(client, "POST", "/api/v1/policies/",
                      actor="admin:ops", token=admin_token,
                      body={"name": f"traffic-policy-{_ts}", "resource_type": "tool",
                            "resource_pattern": "traffic_*", "effect": "ALLOW",
                            "conditions": [], "priority": 5},
                      note="create policy as admin (allow)")
        new_policy_id = r.json().get("id") if r.status_code == 201 else None

        # POST /api/v1/policies/ — alice non-admin (deny)
        await req(client, "POST", "/api/v1/policies/",
                  actor="user:alice", token=alice_token,
                  body={"name": "rogue-policy", "resource_type": "tool",
                        "resource_pattern": "*", "effect": "DENY",
                        "conditions": [], "priority": 0},
                  note="create policy as non-admin (deny)")

        # GET /api/v1/policies/ — list (allow)
        await req(client, "GET", "/api/v1/policies/",
                  actor="user:alice", token=alice_token,
                  note="list policies (allow)")

        # GET /api/v1/policies/{id} — get specific
        await req(client, "GET", "/api/v1/policies/pol-001",
                  actor="user:alice", token=alice_token,
                  note="get policy by id (allow)")

        # PUT /api/v1/policies/{id} — admin updates (allow)
        if new_policy_id:
            await req(client, "PUT", f"/api/v1/policies/{new_policy_id}",
                      actor="admin:ops", token=admin_token,
                      body={"name": f"traffic-policy-{_ts}-v2", "resource_type": "tool",
                            "resource_pattern": "traffic_*", "effect": "ALLOW",
                            "conditions": [], "priority": 10},
                      note="update policy as admin (allow)")

        # PUT /api/v1/policies/{id} — alice updates (deny)
        await req(client, "PUT", "/api/v1/policies/pol-001",
                  actor="user:alice", token=alice_token,
                  body={"name": "hijacked", "resource_type": "tool",
                        "resource_pattern": "*", "effect": "ALLOW",
                        "conditions": [], "priority": 0},
                  note="update policy as non-admin (deny)")

        # DELETE /api/v1/policies/{id} — admin deletes (allow)
        if new_policy_id:
            await req(client, "DELETE", f"/api/v1/policies/{new_policy_id}",
                      actor="admin:ops", token=admin_token,
                      note="delete policy as admin (allow)")

        # DELETE /api/v1/policies/{id} — alice deletes (deny)
        await req(client, "DELETE", "/api/v1/policies/pol-001",
                  actor="user:alice", token=alice_token,
                  note="delete policy as non-admin (deny)")

        # POST /api/v1/policies/evaluate — evaluate
        await req(client, "POST", "/api/v1/policies/evaluate",
                  actor="user:alice", token=alice_token,
                  body={"actor": "user:alice", "resource_type": "tool",
                        "resource_id": "some-tool", "action": "execute"},
                  note="evaluate policy (allow)")

        # POST /api/v1/policies/evaluate — admin evaluates
        await req(client, "POST", "/api/v1/policies/evaluate",
                  actor="admin:ops", token=admin_token,
                  body={"actor": "user:alice", "resource_type": "tool",
                        "resource_id": "http_request", "action": "execute"},
                  note="evaluate policy as admin (allow)")

        # ==================================================================
        # TOOLS (3 routes)
        # ==================================================================

        # GET /api/v1/tools/ — list (allow)
        await req(client, "GET", "/api/v1/tools/",
                  actor="user:alice", token=alice_token,
                  note="list tools (allow)")

        # GET /api/v1/tools/{name} — get specific
        await req(client, "GET", "/api/v1/tools/nonexistent_tool",
                  actor="user:alice", token=alice_token,
                  note="get tool by name (404)")

        # POST /api/v1/tools/{name}/execute — execute
        await req(client, "POST", "/api/v1/tools/nonexistent_tool/execute",
                  actor="user:alice", token=alice_token,
                  body={"arguments": {}},
                  note="execute tool (404 or policy deny)")

        # ==================================================================
        # APPROVALS (5 routes)
        # ==================================================================

        # GET /api/v1/approvals/ — list (allow)
        await req(client, "GET", "/api/v1/approvals/",
                  actor="user:alice", token=alice_token,
                  note="list approvals (allow)")

        # GET /api/v1/approvals/ — bob lists
        await req(client, "GET", "/api/v1/approvals/",
                  actor="user:bob", token=bob_token,
                  note="list approvals as bob (allow)")

        # GET /api/v1/approvals/{id} — nonexistent
        await req(client, "GET", "/api/v1/approvals/nonexistent-appr",
                  actor="user:alice", token=alice_token,
                  note="get nonexistent approval (404)")

        # POST /api/v1/approvals/{id}/approve — nonexistent
        await req(client, "POST", "/api/v1/approvals/nonexistent-appr/approve",
                  actor="user:alice", token=alice_token,
                  body={},
                  note="approve nonexistent (404)")

        # POST /api/v1/approvals/{id}/reject — nonexistent
        await req(client, "POST", "/api/v1/approvals/nonexistent-appr/reject",
                  actor="user:alice", token=alice_token,
                  body={},
                  note="reject nonexistent (404)")

        # GET /api/v1/approvals/runs/{run_id} — approvals for run
        await req(client, "GET", "/api/v1/approvals/runs/run-002",
                  actor="user:alice", token=alice_token,
                  note="get approvals for run (allow)")

        # GET /api/v1/approvals/runs/{run_id} — bob for alice's run
        await req(client, "GET", "/api/v1/approvals/runs/run-002",
                  actor="user:bob", token=bob_token,
                  note="get approvals for other's run (allow, legacy gap)")

        # ==================================================================
        # AUDIT (3 routes)
        # ==================================================================

        # GET /api/v1/audit/ — query (allow)
        await req(client, "GET", "/api/v1/audit/",
                  actor="user:alice", token=alice_token,
                  note="query audit events (allow)")

        # GET /api/v1/audit/trace/{id}
        await req(client, "GET", "/api/v1/audit/trace/nonexistent-trace",
                  actor="user:alice", token=alice_token,
                  note="get audit trace (allow, likely empty)")

        # GET /api/v1/audit/runs/{run_id}/timeline
        await req(client, "GET", "/api/v1/audit/runs/run-002/timeline",
                  actor="user:alice", token=alice_token,
                  note="get audit run timeline (allow)")

        # GET /api/v1/audit/runs/{run_id}/timeline — bob
        await req(client, "GET", "/api/v1/audit/runs/run-002/timeline",
                  actor="user:bob", token=bob_token,
                  note="get audit run timeline as bob (allow, legacy gap)")

        # ==================================================================
        # MULTI-PRINCIPAL CACHE BEHAVIOR
        # ==================================================================

        # Rapid alice calls (should hit cache)
        for i in range(3):
            await req(client, "GET", "/api/v1/tools/",
                      actor="user:alice", token=alice_token,
                      note=f"cache-warm alice req {i+1}")

        # Rapid bob calls (cold then warm)
        for i in range(3):
            await req(client, "GET", "/api/v1/tools/",
                      actor="user:bob", token=bob_token,
                      note=f"cache-warm bob req {i+1}")

        # System engine calls
        await req(client, "GET", "/api/v1/tools/",
                  actor="system:engine", token=engine_token,
                  note="system:engine reads tools (allow)")

        # Clean up: delete the memory record we created
        if mem_id:
            await req(client, "DELETE", f"/api/v1/memory/{mem_id}",
                      actor="user:alice", token=alice_token,
                      note="delete own memory (allow, cleanup)")

    # Print summary
    print(f"\n{'='*80}")
    print(f"Traffic generation complete: {len(results)} requests")
    print(f"{'='*80}\n")

    by_status: dict[int, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1

    print("Status code distribution:")
    for status, count in sorted(by_status.items()):
        print(f"  {status}: {count}")

    print(f"\nDetailed results:")
    for i, r in enumerate(results, 1):
        print(f"  {i:3d}. {r.method:6s} {r.route[:45]:45s} {r.actor:15s} -> {r.status}  {r.note}")


if __name__ == "__main__":
    asyncio.run(run_traffic())
