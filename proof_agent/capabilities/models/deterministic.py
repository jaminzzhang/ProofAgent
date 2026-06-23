from __future__ import annotations

import json

from proof_agent.contracts import ModelRequest, ModelResponse
from proof_agent.contracts.manifest import ModelConfig
from proof_agent.errors import ProofAgentError
from proof_agent.evaluation.demo.deterministic_provider import DeterministicProvider


class DeterministicModelProvider:
    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._provider = DeterministicProvider()

    @classmethod
    def from_config(cls, model_config: ModelConfig) -> DeterministicModelProvider:
        if model_config.name is None:
            raise ProofAgentError(
                "PA_MODEL_001",
                "deterministic model config requires a model name.",
                "Resolve shared/custom model configuration before constructing the provider.",
            )
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
        answer = self._provider.answer(question)
        if (
            request.function_schema is not None
            and request.function_schema.name == "submit_final_answer"
        ):
            answer = json.dumps(
                {
                    "message": answer,
                    "citations": _allowed_citation_refs_from_request(request),
                },
                ensure_ascii=True,
            )
        return ModelResponse(
            content=answer,
            provider_name=self.provider_name,
            model_name=self.model_name,
            finish_reason="stop",
        )


def _last_user_message(request: ModelRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content
    return request.messages[-1].content if request.messages else ""


def _allowed_citation_refs_from_request(request: ModelRequest) -> list[str]:
    refs: list[str] = []
    capture = False
    for line in _last_user_message(request).splitlines():
        if line.strip() == "Allowed citation refs:":
            capture = True
            continue
        if not capture:
            continue
        if not line.startswith("- "):
            break
        ref = line[2:].strip()
        if ref:
            refs.append(ref)
    return refs[:1]
