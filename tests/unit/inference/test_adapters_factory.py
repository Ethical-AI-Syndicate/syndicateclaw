from syndicateclaw.inference.adapters.factory import adapter_for
from syndicateclaw.inference.adapters.ollama import OllamaAdapter
from syndicateclaw.inference.adapters.openai_compatible import OpenAICompatibleAdapter
from syndicateclaw.inference.types import AdapterProtocol


def test_adapter_factory_maps_protocols() -> None:
    assert isinstance(adapter_for(AdapterProtocol.OPENAI_COMPATIBLE), OpenAICompatibleAdapter)
    assert isinstance(adapter_for(AdapterProtocol.OLLAMA_NATIVE), OllamaAdapter)
