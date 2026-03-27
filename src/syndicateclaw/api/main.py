from __future__ import annotations

import asyncio
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, cast

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
from sqlalchemy import text

from syndicateclaw.api.middleware import (
    AuditMiddleware,
    PrometheusMetricsMiddleware,
    RequestIDMiddleware,
)
from syndicateclaw.api.rate_limit import RateLimitMiddleware
from syndicateclaw.api.routes import ALL_ROUTERS
from syndicateclaw.authz.shadow_middleware import ShadowRBACMiddleware
from syndicateclaw.config import Settings
from syndicateclaw.middleware import RBACMiddleware

logger = structlog.get_logger(__name__)

VERSION = "0.1.0"


async def configure_system_engine(session_factory: Any) -> None:
    """Ensure system:engine has run:control + tool:execute before serving traffic."""
    from sqlalchemy import select

    from syndicateclaw.db.models import Principal, Role, RoleAssignment

    async with session_factory() as session, session.begin():
        principal = (
            await session.execute(
                select(Principal).where(
                    Principal.principal_type == "service",
                    Principal.name == "system:engine",
                )
            )
        ).scalar_one_or_none()
        if principal is None:
            principal = Principal(
                principal_type="service",
                name="system:engine",
                enabled=True,
            )
            session.add(principal)
            await session.flush()

        role = (
            await session.execute(
                select(Role).where(
                    Role.name == "system_engine_runtime",
                    Role.scope_type == "PLATFORM",
                )
            )
        ).scalar_one_or_none()
        if role is None:
            role = Role(
                name="system_engine_runtime",
                description="Runtime permissions for system:engine service account",
                built_in=True,
                permissions=["run:control", "tool:execute"],
                inherits_from=None,
                display_base=None,
                scope_type="PLATFORM",
                created_by="system",
            )
            session.add(role)
            await session.flush()

        assignment = (
            await session.execute(
                select(RoleAssignment).where(
                    RoleAssignment.principal_id == principal.id,
                    RoleAssignment.role_id == role.id,
                    RoleAssignment.scope_type == "PLATFORM",
                    RoleAssignment.scope_id == "platform",
                    RoleAssignment.revoked.is_(False),
                )
            )
        ).scalar_one_or_none()
        if assignment is None:
            session.add(
                RoleAssignment(
                    principal_id=principal.id,
                    role_id=role.id,
                    scope_type="PLATFORM",
                    scope_id="platform",
                    granted_by="system",
                    revoked=False,
                )
            )


def _configure_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(0),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _configure_otel(app: FastAPI, endpoint: str) -> None:
    try:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": "syndicateclaw"})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
        )

        from opentelemetry import trace

        trace.set_tracer_provider(provider)
        FastAPIInstrumentor.instrument_app(app)
        logger.info("otel.configured", endpoint=endpoint)
    except Exception:
        logger.warning("otel.setup_failed", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    import redis.asyncio as aioredis
    from redis.asyncio import Redis

    from syndicateclaw.approval.service import ApprovalService
    from syndicateclaw.audit.service import AuditService
    from syndicateclaw.db.base import get_engine, get_session_factory
    from syndicateclaw.memory.service import MemoryService
    from syndicateclaw.orchestrator.engine import WorkflowEngine
    from syndicateclaw.orchestrator.handlers import BUILTIN_HANDLERS
    from syndicateclaw.policy.engine import PolicyEngine
    from syndicateclaw.tools.builtin import BUILTIN_TOOLS
    from syndicateclaw.tools.executor import ToolExecutor
    from syndicateclaw.tools.registry import ToolRegistry

    settings = Settings()
    _configure_structlog()

    engine = get_engine(settings.database_url)
    try:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)
        logger.info("otel.sqlalchemy_instrumented")
    except Exception:
        logger.debug("otel.sqlalchemy_instrument_skipped", exc_info=True)
    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
        logger.info("otel.httpx_instrumented")
    except Exception:
        logger.debug("otel.httpx_instrument_skipped", exc_info=True)
    session_factory = get_session_factory(engine)
    await configure_system_engine(session_factory)
    redis_client = cast(
        Redis,
        aioredis.from_url(settings.redis_url, decode_responses=True),  # type: ignore[no-untyped-call]
    )

    from syndicateclaw.security.signing import derive_signing_key

    signing_key = derive_signing_key(settings.secret_key)

    asymmetric_keypair = None
    if settings.ed25519_private_key_path:
        from syndicateclaw.security.signing import SigningKeyPair
        key_path = Path(settings.ed25519_private_key_path)
        if not key_path.exists():
            raise RuntimeError(
                f"Ed25519 private key not found at {key_path}. "
                "Set SYNDICATECLAW_ED25519_PRIVATE_KEY_PATH to a valid PEM file."
            )
        asymmetric_keypair = SigningKeyPair(private_key_bytes=key_path.read_bytes())
        logger.info("security.ed25519_key_loaded", path=str(key_path))
    elif settings.require_asymmetric_signing:
        raise RuntimeError(
            "SYNDICATECLAW_REQUIRE_ASYMMETRIC_SIGNING is enabled but "
            "SYNDICATECLAW_ED25519_PRIVATE_KEY_PATH is not set. "
            "Provide an Ed25519 private key or disable the requirement."
        )

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis_client = redis_client

    audit_service = AuditService(session_factory, signing_key=signing_key)
    memory_service = MemoryService(
        session_factory,
        redis_client=redis_client,
        max_value_bytes=settings.memory_max_value_bytes,
        max_key_length=settings.memory_max_key_length,
        max_namespace_length=settings.memory_max_namespace_length,
    )
    policy_engine = PolicyEngine(session_factory)
    from syndicateclaw.approval.authority import ApprovalAuthorityResolver
    authority_resolver = ApprovalAuthorityResolver(session_factory=session_factory)
    approval_service = ApprovalService(
        session_factory,
        authority_resolver=authority_resolver,
    )

    from syndicateclaw.audit.ledger import DecisionLedger
    from syndicateclaw.orchestrator.snapshots import InputSnapshotStore

    decision_ledger = DecisionLedger(session_factory, signing_key=signing_key)
    snapshot_store = InputSnapshotStore(session_factory)

    tool_registry = ToolRegistry()
    tool_executor = ToolExecutor(
        tool_registry, policy_engine, audit_service,
        decision_ledger=decision_ledger,
        snapshot_store=snapshot_store,
    )

    workflow_engine = WorkflowEngine(
        BUILTIN_HANDLERS,
        checkpoint_store=None,
        audit_service=audit_service,
        signing_key=signing_key,
    )

    for tool, handler in BUILTIN_TOOLS:
        tool_registry.register(tool, handler)

    repo_root = Path(__file__).resolve().parents[2]
    yaml_path = Path(settings.providers_yaml_path or (repo_root / "providers.yaml.example"))
    if not yaml_path.exists():
        yaml_path.write_text("inference_enabled: false\nproviders: []\n", encoding="utf-8")

    from syndicateclaw.inference.catalog import ModelCatalog
    from syndicateclaw.inference.config_loader import (
        ProviderConfigLoader,
        validate_provider_env_vars,
    )
    from syndicateclaw.inference.config_schema import ProviderSystemConfig
    from syndicateclaw.inference.idempotency import IdempotencyStore
    from syndicateclaw.inference.registry import ProviderRegistry
    from syndicateclaw.inference.service import ProviderService
    from syndicateclaw.messaging.router import MessageRouter
    from syndicateclaw.services.agent_service import AgentService
    from syndicateclaw.services.message_service import MessageService
    from syndicateclaw.services.streaming_token_service import (
        StreamingTokenRepository,
        StreamingTokenService,
    )
    from syndicateclaw.services.subscription_service import SubscriptionService
    from syndicateclaw.tasks.message_delivery import run_message_delivery_loop
    from syndicateclaw.tools.inference_tools import build_inference_tools

    provider_config_loader = ProviderConfigLoader(yaml_path)
    try:
        provider_config_loader.load_and_activate()
    except Exception:
        logger.warning("provider_config.initial_load_failed", exc_info=True)
        provider_config_loader.activate(ProviderSystemConfig(inference_enabled=False, providers=()))

    _cfg, _ver = provider_config_loader.current()
    validate_provider_env_vars(_cfg)
    inference_catalog = ModelCatalog()
    inference_catalog.replace_from_yaml_static(_cfg, snapshot_version=_ver)
    provider_registry = ProviderRegistry(_cfg)
    idempotency_store = IdempotencyStore(session_factory)
    provider_service = ProviderService(
        loader=provider_config_loader,
        catalog=inference_catalog,
        registry=provider_registry,
        policy_engine=policy_engine,
        audit_service=audit_service,
        idempotency_store=idempotency_store,
    )
    streaming_token_repository = StreamingTokenRepository(session_factory)
    streaming_token_service = StreamingTokenService(
        streaming_token_repository,
        streaming_token_ttl_seconds=settings.streaming_token_ttl_seconds,
    )
    agent_service = AgentService(
        session_factory,
        heartbeat_timeout_seconds=getattr(settings, "agent_heartbeat_timeout_seconds", 60),
    )
    subscription_service = SubscriptionService(session_factory, agent_service=agent_service)
    message_router = MessageRouter(
        session_factory,
        max_hops=settings.message_max_hops,
    )
    message_service = MessageService(
        session_factory,
        agent_service=agent_service,
        subscription_service=subscription_service,
        router=message_router,
        redis_client=redis_client,
    )
    for tool, handler in build_inference_tools(provider_service):
        tool_registry.register(tool, handler)

    app.state.provider_config_loader = provider_config_loader
    app.state.inference_catalog = inference_catalog
    app.state.provider_registry = provider_registry
    app.state.provider_service = provider_service
    app.state.streaming_token_service = streaming_token_service
    app.state.agent_service = agent_service
    app.state.subscription_service = subscription_service
    app.state.message_service = message_service

    app.state.audit_service = audit_service
    app.state.memory_service = memory_service
    app.state.policy_engine = policy_engine
    app.state.approval_service = approval_service
    app.state.tool_registry = tool_registry
    app.state.tool_executor = tool_executor
    app.state.workflow_engine = workflow_engine
    app.state.decision_ledger = decision_ledger
    app.state.snapshot_store = snapshot_store
    app.state.signing_key = signing_key
    app.state.asymmetric_keypair = asymmetric_keypair

    from syndicateclaw.security.api_keys import ApiKeyService
    from syndicateclaw.tasks.agent_heartbeat import run_agent_heartbeat_expiry_loop

    api_key_service = ApiKeyService(session_factory)
    app.state.api_key_service = api_key_service

    heartbeat_task = asyncio.create_task(
        run_agent_heartbeat_expiry_loop(
            agent_service,
            interval_seconds=settings.agent_heartbeat_check_interval,
        ),
        name="agent-heartbeat-expiry-loop",
    )
    message_delivery_task = asyncio.create_task(
        run_message_delivery_loop(
            message_service,
            session_factory,
            poll_interval_seconds=5,
        ),
        name="message-delivery-loop",
    )

    logger.info(
        "app.startup",
        version=VERSION,
        tools_registered=len(tool_registry),
    )

    if settings.otel_endpoint:
        _configure_otel(app, settings.otel_endpoint)

    yield

    logger.info("app.shutdown")
    heartbeat_task.cancel()
    with suppress(asyncio.CancelledError):
        await heartbeat_task
    message_delivery_task.cancel()
    with suppress(asyncio.CancelledError):
        await message_delivery_task
    await engine.dispose()
    await redis_client.aclose()


def create_app() -> FastAPI:
    settings = Settings()

    app = FastAPI(
        title="SyndicateClaw",
        version=VERSION,
        description=(
            "Production-oriented agent orchestration platform with "
            "stateful graph-based workflows"
        ),
        lifespan=lifespan,
    )

    app.add_middleware(PrometheusMetricsMiddleware)
    app.add_middleware(AuditMiddleware)
    app.add_middleware(RBACMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(ShadowRBACMiddleware)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    for router in ALL_ROUTERS:
        app.include_router(router)

    app.mount("/metrics", make_asgi_app())

    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        """Liveness probe — process is running."""
        return {"status": "ok", "version": VERSION}

    @app.get("/readyz", tags=["system"], response_model=None)
    async def readyz(request: Request) -> dict[str, Any] | JSONResponse:
        """Readiness probe — all dependencies are reachable."""
        checks: dict[str, str] = {}
        healthy = True

        try:
            sf = request.app.state.session_factory
            async with sf() as session:
                await session.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as e:
            checks["database"] = f"error: {e}"
            healthy = False

        try:
            rc = request.app.state.redis_client
            await rc.ping()
            checks["redis"] = "ok"
        except Exception as e:
            checks["redis"] = f"error: {e}"
            healthy = False

        pe = getattr(request.app.state, "policy_engine", None)
        checks["policy_engine"] = "ok" if pe is not None else "missing"
        if pe is None:
            healthy = False

        dl = getattr(request.app.state, "decision_ledger", None)
        checks["decision_ledger"] = "ok" if dl is not None else "missing"
        if dl is None:
            healthy = False

        rate_limit_ok = checks.get("redis") == "ok"
        if rate_limit_ok:
            checks["rate_limiting"] = "ok"
        else:
            checks["rate_limiting"] = "degraded (fail-open)"
            settings = getattr(request.app.state, "settings", None)
            if settings and getattr(settings, "rate_limit_strict", False):
                checks["rate_limiting"] = "unavailable (strict mode)"
                healthy = False

        if not healthy:
            return JSONResponse(
                status_code=503,
                content={"status": "degraded", "version": VERSION, "checks": checks},
            )

        return {"status": "ready", "version": VERSION, "checks": checks}

    @app.get("/api/v1/info", tags=["system"])
    async def info() -> dict[str, object]:
        return {
            "title": app.title,
            "version": VERSION,
            "python_version": sys.version,
            "docs_url": app.docs_url or "/docs",
        }

    return app


app = create_app()
