from __future__ import annotations

from typing import Protocol, Self

from proof_agent.contracts import ModelRequest, ModelResponse
from proof_agent.contracts.manifest import ModelConfig


class ModelProvider(Protocol):
    @classmethod
    def from_config(cls, model_config: ModelConfig) -> Self: ...

    @property
    def provider_name(self) -> str: ...

    @property
    def model_name(self) -> str: ...

    def estimate_tokens(self, request: ModelRequest) -> int | None: ...

    def generate(self, request: ModelRequest) -> ModelResponse: ...
