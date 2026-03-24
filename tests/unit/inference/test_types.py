import pytest

from syndicateclaw.inference.types import (
    ChatInferenceRequest,
    ChatMessage,
    DataSensitivity,
    EmbeddingInferenceRequest,
    ModelDescriptor,
    ModelPinning,
)


def test_chat_request_defaults():
    r = ChatInferenceRequest(
        messages=[ChatMessage(role="user", content="hi")],
        actor="user:alice",
        trace_id="trace-1",
    )
    assert r.model_pinning == ModelPinning.PREFERRED
    assert r.sensitivity == DataSensitivity.INTERNAL


def test_embedding_request_defaults_pinning_required():
    r = EmbeddingInferenceRequest(
        inputs=["hello"],
        actor="user:alice",
        trace_id="trace-1",
    )
    assert r.model_pinning == ModelPinning.REQUIRED


def test_embedding_dimensions_validated_when_flag_set():
    m = ModelDescriptor(
        model_id="e1",
        name="E",
        provider_id="p",
        is_embedding_model=True,
        embedding_dimensions=768,
    )
    m.validate_embedding_dimensions()

    bad = ModelDescriptor(
        model_id="e2",
        name="E2",
        provider_id="p",
        is_embedding_model=True,
        embedding_dimensions=None,
    )
    with pytest.raises(ValueError, match="embedding_dimensions"):
        bad.validate_embedding_dimensions()
