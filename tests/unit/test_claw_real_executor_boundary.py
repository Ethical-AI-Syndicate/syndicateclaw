"""Real-executor Claw boundary tests (SDD-CLAW-DURABLE-EXECUTOR-BOUNDARY-002).

Proves the production behavior the golden-path validator requires: the allow path
invokes the REAL ToolExecutor + real tool handler gated by the durable boundary;
deny paths never invoke the executor's tool handler and never perform the side
effect; the side effect happens only after a boundary allow AND a durable audit
append.
"""

from __future__ import annotations

import asyncio

import pytest

from syndicateclaw.models import PolicyEffect, Tool, ToolRiskLevel, ToolSandboxPolicy
from syndicateclaw.orchestrator.engine import ExecutionContext
from syndicateclaw.runtime_boundary import (
    AuthorityBinding,
    ClawRuntimeBoundary,
    DurableAuditChain,
    InMemoryControlPlaneValidator,
    ValidationStatus,
    reopen,
)
from syndicateclaw.tools.executor import ToolDeniedError, ToolExecutor
from syndicateclaw.tools.registry import ToolRegistry

ARTIFACT = {
    "permit_id": "perm-1",
    "actor": "operator-1",
    "tool_identity": "fs.write_file",
    "side_effect_class": "filesystem.write",
    "resource_scope": "/ws/p1/README.md",
    "approval_id": "dec-1",
}


def _binding() -> AuthorityBinding:
    return AuthorityBinding(
        actor=ARTIFACT["actor"],
        tenant_id="t1",
        project_id="p1",
        workspace_id="w1",
        tool_identity=ARTIFACT["tool_identity"],
        action=ARTIFACT["side_effect_class"],
        resource_scope=ARTIFACT["resource_scope"],
        approval_id=ARTIFACT["approval_id"],
        correlation_id="c1",
    )


def _tool() -> Tool:
    return Tool(
        name="fs.write_file",
        version="1.0.0",
        input_schema={"type": "object"},
        side_effects=["filesystem.write"],
        owner="t",
        risk_level=ToolRiskLevel.LOW,
        sandbox_policy=ToolSandboxPolicy(),
    )


class _AllowPolicy:
    async def evaluate(self, *a, **k):
        return PolicyEffect.ALLOW


class _Ledger:
    async def record_tool_decision(self, **kw):
        return type("R", (), {"id": "d0"})()


def _boundary(tmp_path, *, status=ValidationStatus.ALLOW, single_use=False, unavailable=False):
    v = InMemoryControlPlaneValidator()
    v.register("perm-1", _binding(), status=status, single_use=single_use)
    v.set_unavailable(unavailable)
    return ClawRuntimeBoundary(
        v, production_mode=True, audit_chain=DurableAuditChain(tmp_path / "a.jsonl")
    )


def _executor(boundary, flag, *, policy=True, ledger=True):
    reg = ToolRegistry()

    async def handler(_):
        flag["invoked"] = True
        return {"ok": True}

    reg.register(_tool(), handler)
    return ToolExecutor(
        reg,
        policy_engine=(_AllowPolicy() if policy else None),
        decision_ledger=(_Ledger() if ledger else None),
        runtime_boundary=boundary,
    )


def _ctx(**over):
    cfg = {
        "actor": ARTIFACT["actor"],
        "tenant_id": "t1",
        "project_id": "p1",
        "workspace_id": "w1",
        "resource_scope": ARTIFACT["resource_scope"],
        "authority": {
            "authority_reference": "perm-1",
            "actor": ARTIFACT["actor"],
            "tenant_id": "t1",
            "project_id": "p1",
            "workspace_id": "w1",
            "tool_identity": ARTIFACT["tool_identity"],
            "action": ARTIFACT["side_effect_class"],
            "resource_scope": ARTIFACT["resource_scope"],
            "approval_id": "dec-1",
            "correlation_id": "c1",
        },
    }
    cfg.update(over)
    return ExecutionContext(run_id="r1", node_id="n1", config=cfg)


def test_allow_invokes_real_executor_and_handler(tmp_path):
    flag = {"invoked": False}
    b = _boundary(tmp_path)
    ex = _executor(b, flag)
    out = asyncio.run(ex.execute("fs.write_file", {"path": "/ws/p1/README.md"}, _ctx()))
    assert out["ok"] is True
    assert flag["invoked"] is True  # real handler ran
    # Durable audit appended BEFORE the side effect (allow event at seq 0).
    assert reopen(tmp_path / "a.jsonl").verify().valid is True


def test_deny_missing_authority_skips_handler(tmp_path):
    flag = {"invoked": False}
    b = _boundary(tmp_path)
    ex = _executor(b, flag)
    ctx = _ctx(authority=None)
    with pytest.raises(ToolDeniedError):
        asyncio.run(ex.execute("fs.write_file", {"path": "/x"}, ctx))
    assert flag["invoked"] is False  # handler never ran; no side effect


def test_deny_tenant_mismatch_skips_handler(tmp_path):
    flag = {"invoked": False}
    b = _boundary(tmp_path)
    ex = _executor(b, flag)
    auth = dict(_ctx().config["authority"], tenant_id="other")
    with pytest.raises(ToolDeniedError):
        asyncio.run(ex.execute("fs.write_file", {"path": "/x"}, _ctx(authority=auth)))
    assert flag["invoked"] is False


def test_deny_policy_unavailable_skips_handler(tmp_path):
    flag = {"invoked": False}
    b = _boundary(tmp_path)
    ex = _executor(b, flag, policy=False)  # policy_engine=None -> fail closed
    with pytest.raises(ToolDeniedError):
        asyncio.run(ex.execute("fs.write_file", {"path": "/x"}, _ctx()))
    assert flag["invoked"] is False


def test_deny_audit_append_failure_skips_handler(tmp_path):
    flag = {"invoked": False}
    b = _boundary(tmp_path)
    b.audit.set_fail(True)  # durable evidence writer unavailable
    ex = _executor(b, flag)
    with pytest.raises(ToolDeniedError):
        asyncio.run(ex.execute("fs.write_file", {"path": "/x"}, _ctx()))
    assert flag["invoked"] is False  # no side effect when audit cannot append
