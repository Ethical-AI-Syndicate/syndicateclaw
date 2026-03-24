"""Provider integration domain types.

See: docs/superpowers/specs/2025-03-24-provider-integration-architecture-design.md
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field
from ulid import ULID

from syndicateclaw.models import PolicyEffect


def _utcnow() -> datetime:
    return datetime.now(UTC)


class InferenceCapability(str, enum.Enum):
    CHAT = "chat"
    EMBEDDING = "embedding"


class AdapterProtocol(str, enum.Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    OLLAMA_NATIVE = "ollama_native"


class ProviderType(str, enum.Enum):
    LOCAL = "local"
    REMOTE = "remote"


class ProviderStatus(str, enum.Enum):
    ACTIVE = "active"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"


class HealthStrategy(str, enum.Enum):
    MODELS_LIST = "models_list"
    CHAT_NOOP = "chat_noop"
    EMBED_NOOP = "embed_noop"
    TCP_CONNECT = "tcp_connect"
    DISABLED = "disabled"
    TAGS_LIST = "tags_list"


class InferenceStatus(str, enum.Enum):
    PENDING = "pending"
    ROUTING = "routing"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


class DataSensitivity(str, enum.Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class ConcurrencyPolicy(str, enum.Enum):
    REJECT = "reject"
    QUEUE = "queue"
    SHED = "shed"


class ErrorCategory(str, enum.Enum):
    POLICY = "policy"
    PROVIDER = "provider"
    TRANSPORT = "transport"
    TIMEOUT = "timeout"
    VALIDATION = "validation"
    UNKNOWN = "unknown"


class CircuitState(str, enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ProviderTrustTier(str, enum.Enum):
    TRUSTED = "trusted"
    RESTRICTED = "restricted"
    UNTRUSTED = "untrusted"


class RoutingFailureReason(str, enum.Enum):
    NO_MODELS = "no_models"
    NO_PROVIDER_MATCH = "no_provider_match"
    POLICY_DENIED = "policy_denied"
    SENSITIVITY_BLOCKED = "sensitivity_blocked"
    CIRCUIT_OPEN = "circuit_open"
    HEALTH_UNAVAILABLE = "health_unavailable"
    PIN_MISMATCH = "pin_mismatch"
    NO_CANDIDATES = "no_candidates"
    ALL_CANDIDATES_FAILED = "all_candidates_failed"
    UNKNOWN = "unknown"


class CatalogEntryStatus(str, enum.Enum):
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class ModelPinning(str, enum.Enum):
    REQUIRED = "required"
    PREFERRED = "preferred"
    NONE = "none"


# --- Config (declarative) ---


class ProviderAuthConfig(BaseModel):
    env_var: str | None = None
    header_name: str = "Authorization"
    header_prefix: str = "Bearer "
    additional_headers: dict[str, str] = Field(default_factory=dict)


class ProviderTimeoutProfile(BaseModel):
    connect_seconds: float = 5.0
    read_seconds: float = 60.0
    chat_seconds: float = 120.0
    embedding_seconds: float = 30.0


class ProviderConfig(BaseModel):
    """Runtime provider instance — loaded from YAML; not overridden by DB in Phase 1."""

    id: str
    name: str
    provider_type: ProviderType
    adapter_protocol: AdapterProtocol
    base_url: str
    auth: ProviderAuthConfig | None = None
    timeout: ProviderTimeoutProfile = Field(default_factory=ProviderTimeoutProfile)
    capabilities: list[InferenceCapability]
    allowed_models: list[str] | None = None
    denied_models: list[str] | None = None
    health_strategy: HealthStrategy = HealthStrategy.MODELS_LIST
    enabled: bool = True
    max_concurrent_requests: int = 50
    concurrency_policy: ConcurrencyPolicy = ConcurrencyPolicy.REJECT
    queue_timeout_seconds: float | None = None
    max_allowed_sensitivity: DataSensitivity = DataSensitivity.INTERNAL
    trust_tier: ProviderTrustTier = ProviderTrustTier.RESTRICTED
    config_version: str = "1"


class ModelCapabilities(BaseModel):
    reasoning: bool = False
    tool_call: bool = False
    structured_output: bool = False
    temperature: bool = True


class ModelCost(BaseModel):
    input_per_million: float = 0.0
    output_per_million: float = 0.0
    cache_read_per_million: float = 0.0


class ModelLimits(BaseModel):
    context_window: int = 0
    max_output: int = 0


class ModelDescriptor(BaseModel):
    model_id: str
    name: str
    family: str = ""
    provider_id: str
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    modalities_input: list[str] = Field(default_factory=list)
    modalities_output: list[str] = Field(default_factory=list)
    cost: ModelCost = Field(default_factory=ModelCost)
    limits: ModelLimits = Field(default_factory=ModelLimits)
    open_weights: bool = False
    embedding_dimensions: int | None = None
    is_embedding_model: bool = False

    def validate_embedding_dimensions(self) -> None:
        """Call at catalog ingestion: embedding models must declare dimensions."""
        if self.is_embedding_model and self.embedding_dimensions is None:
            raise ValueError("embedding_dimensions required for embedding models")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatInferenceRequest(BaseModel):
    messages: list[ChatMessage]
    model_id: str | None = None
    provider_id: str | None = None
    capability: Literal["chat"] = "chat"
    temperature: float | None = None
    max_tokens: int | None = None
    actor: str
    scope_type: str = "PLATFORM"
    scope_id: str = "default"
    sensitivity: DataSensitivity = DataSensitivity.INTERNAL
    trace_id: str
    idempotency_key: str | None = None
    model_pinning: ModelPinning = ModelPinning.PREFERRED


class EmbeddingInferenceRequest(BaseModel):
    inputs: list[str]
    model_id: str | None = None
    provider_id: str | None = None
    capability: Literal["embedding"] = "embedding"
    actor: str
    scope_type: str = "PLATFORM"
    scope_id: str = "default"
    sensitivity: DataSensitivity = DataSensitivity.INTERNAL
    trace_id: str
    idempotency_key: str | None = None
    model_pinning: ModelPinning = ModelPinning.REQUIRED


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatInferenceResponse(BaseModel):
    inference_id: str
    provider_id: str
    model_id: str
    content: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None
    latency_ms: float = 0.0
    routing_decision_id: str = ""
    policy_decision_id: str = ""


class EmbeddingInferenceResponse(BaseModel):
    inference_id: str
    provider_id: str
    model_id: str
    embeddings: list[list[float]]
    dimensions: int
    usage: TokenUsage | None = None
    latency_ms: float = 0.0
    routing_decision_id: str = ""
    policy_decision_id: str = ""


class InferenceRequestEnvelope(BaseModel):
    idempotency_key: str
    request_hash: str
    first_seen_at: datetime = Field(default_factory=_utcnow)
    last_seen_at: datetime = Field(default_factory=_utcnow)
    status: InferenceStatus = InferenceStatus.PENDING
    inference_id: str = ""
    system_config_version: str = ""


class PolicyGateResult(BaseModel):
    gate: Literal["tool", "inference_capability", "provider_model", "execution_revalidation"]
    decision_id: str | None = None
    effect: PolicyEffect | Literal["pass", "fail"]
    resource_type: str
    resource_id: str
    action: str
    evaluated_at: datetime = Field(default_factory=_utcnow)
    cached: bool = False
    context_hash: str = ""


class PolicyChain(BaseModel):
    chain_id: str
    inference_id: str
    gates: list[PolicyGateResult] = Field(default_factory=list)


class RoutingDecision(BaseModel):
    id: str
    selected_provider_id: str
    selected_model_id: str
    selection_reason: str = ""
    fallback_chain: list[tuple[str, str]] = Field(default_factory=list)
    fallback_position: int = 0
    override_applied: bool = False
    override_rejected_reason: str | None = None
    candidates_considered: int = 0
    candidates_filtered: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


class InferenceDecisionRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(ULID()))
    inference_id: str
    capability: InferenceCapability
    actor: str
    scope_type: str
    scope_id: str
    requested_provider_id: str | None = None
    requested_model_id: str | None = None
    resolved_provider_id: str = ""
    resolved_model_id: str = ""
    resolved_provider_type: ProviderType | None = None
    resolved_model_alias: str | None = None
    adapter_protocol: AdapterProtocol | None = None
    adapter_version: str = ""
    provider_config_version: str = ""
    catalog_snapshot_version: str | None = None
    routing_decision_id: str = ""
    policy_decision_id: str = ""
    policy_chain_id: str = ""
    request_payload_hash: str = ""
    response_payload_hash: str | None = None
    status: InferenceStatus = InferenceStatus.PENDING
    routing_latency_ms: float | None = None
    provider_latency_ms: float | None = None
    queue_latency_ms: float | None = None
    parent_decision_id: str | None = None
    attempt_number: int = 1
    fallback_used: bool = False
    error_category: ErrorCategory | None = None
    retryable: bool | None = None
    created_at: datetime = Field(default_factory=_utcnow)
