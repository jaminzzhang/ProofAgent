from __future__ import annotations

from proof_agent.contracts import ModelRequest, ModelResponse
from proof_agent.contracts.manifest import ModelConfig
from proof_agent.demo.deterministic_provider import DeterministicProvider


class DeterministicModelProvider:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._provider = DeterministicProvider()

    @classmethod
    def from_config(cls, model_config: ModelConfig) -> DeterministicModelProvider:
        return cls(model_config.name)

    @property
    def provider_name(self) -> str:
        return "deterministic"

    @property
    def model_name(self) -> str:
        return self._model_name

    def estimate_tokens(self, request: ModelRequest) -> int | None:
        return None

    def generate(self, request: ModelRequest) -> ModelResponse:
        question = str(request.metadata.get("question") or _last_user_message(request))
        return ModelResponse(
            content=self._provider.answer(question),
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


def _last_user_message(request: ModelRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content
    return request.messages[-1].content if request.messages else ""
