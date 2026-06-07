"""Tests for ProofAgentLLM bridge adapter."""

import pytest
from llama_index.core.base.llms.types import (
    ChatMessage,
    ChatResponse,
    CompletionResponse,
)
from llama_index.core.llms import MessageRole

from proof_agent.capabilities.models.llama_index_bridge import ProofAgentLLM
from proof_agent.contracts import ModelCallRole, ModelResponse


class MockModelProvider:
    """Mock ModelProvider for testing."""

    def __init__(
        self,
        provider_name: str = "mock_provider",
        model_name: str = "mock_model",
        responses: list[ModelResponse] | None = None,
    ):
        self._provider_name = provider_name
        self._model_name = model_name
        self._responses = responses or []
        self._calls: list[tuple] = []

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def generate(self, request) -> ModelResponse:
        self._calls.append(request)
        if not self._responses:
            return ModelResponse(
                content="Mock response",
                provider_name=self._provider_name,
                model_name=self._model_name,
            )
        return self._responses.pop(0)


class TestProofAgentLLM:
    """Test ProofAgentLLM bridge adapter."""

    def test_instantiation_with_provider_and_role(self) -> None:
        """ProofAgentLLM can be instantiated with ModelProvider and ModelCallRole."""
        provider = MockModelProvider()
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_PLANNER)

        assert llm._provider is provider
        assert llm._role == ModelCallRole.RETRIEVAL_PLANNER

    def test_complete_converts_prompt_to_model_request(self) -> None:
        """complete() converts prompt to ModelRequest and returns CompletionResponse."""
        provider = MockModelProvider(
            provider_name="test_provider",
            model_name="test_model",
            responses=[
                ModelResponse(
                    content="Test completion response",
                    provider_name="test_provider",
                    model_name="test_model",
                )
            ],
        )
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_PLANNER)

        response = llm.complete("Test prompt")

        assert isinstance(response, CompletionResponse)
        assert response.text == "Test completion response"
        assert len(provider._calls) == 1

        # Verify the request was constructed correctly
        request = provider._calls[0]
        assert request.provider == "test_provider"
        assert request.model == "test_model"
        assert len(request.messages) == 1
        assert request.messages[0].role.value == "user"
        assert request.messages[0].content == "Test prompt"

    def test_complete_propagates_timeout_and_invokes_progress_callback_around_provider_call(
        self,
    ) -> None:
        """complete() renews ownership before and after one bounded provider call."""
        provider = MockModelProvider()
        progress: list[str] = []
        llm = ProofAgentLLM(
            model_provider=provider,
            role=ModelCallRole.INGESTION,
            timeout_seconds=17.5,
            progress_callback=lambda: progress.append("renewed"),
        )

        llm.complete("Summarize")

        assert provider._calls[0].timeout_seconds == 17.5
        assert progress == ["renewed", "renewed"]

    def test_complete_preserves_token_usage(self) -> None:
        """complete() preserves token usage in additional_kwargs."""
        from proof_agent.contracts import TokenUsage

        provider = MockModelProvider(
            responses=[
                ModelResponse(
                    content="Response with tokens",
                    provider_name="test",
                    model_name="test",
                    token_usage=TokenUsage(
                        input_tokens=10,
                        output_tokens=20,
                        total_tokens=30,
                    ),
                )
            ],
        )
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.INGESTION)

        response = llm.complete("Prompt")

        assert response.additional_kwargs["token_usage"] == {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
        }

    def test_complete_preserves_finish_reason(self) -> None:
        """complete() preserves finish_reason in additional_kwargs."""
        provider = MockModelProvider(
            responses=[
                ModelResponse(
                    content="Response",
                    provider_name="test",
                    model_name="test",
                    finish_reason="stop",
                )
            ],
        )
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.ROUTING)

        response = llm.complete("Prompt")

        assert response.additional_kwargs["finish_reason"] == "stop"

    def test_complete_preserves_refusal_reason(self) -> None:
        """complete() preserves refusal_reason in additional_kwargs."""
        provider = MockModelProvider(
            responses=[
                ModelResponse(
                    content="",
                    provider_name="test",
                    model_name="test",
                    refusal_reason="Content policy violation",
                )
            ],
        )
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_EVALUATOR)

        response = llm.complete("Prompt")

        assert response.additional_kwargs["refusal_reason"] == "Content policy violation"

    def test_chat_converts_messages_to_model_request(self) -> None:
        """chat() converts ChatMessage list to ModelRequest and returns ChatResponse."""
        provider = MockModelProvider(
            provider_name="chat_provider",
            model_name="chat_model",
            responses=[
                ModelResponse(
                    content="Assistant response",
                    provider_name="chat_provider",
                    model_name="chat_model",
                )
            ],
        )
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_PLANNER)

        messages = [
            ChatMessage(role=MessageRole.SYSTEM, content="You are helpful"),
            ChatMessage(role=MessageRole.USER, content="Hello"),
        ]

        response = llm.chat(messages)

        assert isinstance(response, ChatResponse)
        assert response.message.role == MessageRole.ASSISTANT
        assert response.message.content == "Assistant response"
        assert len(provider._calls) == 1

        # Verify the request was constructed correctly
        request = provider._calls[0]
        assert len(request.messages) == 2
        assert request.messages[0].role.value == "system"
        assert request.messages[0].content == "You are helpful"
        assert request.messages[1].role.value == "user"
        assert request.messages[1].content == "Hello"

    def test_chat_preserves_token_usage(self) -> None:
        """chat() preserves token usage in additional_kwargs."""
        from proof_agent.contracts import TokenUsage

        provider = MockModelProvider(
            responses=[
                ModelResponse(
                    content="Chat response",
                    provider_name="test",
                    model_name="test",
                    token_usage=TokenUsage(
                        input_tokens=15,
                        output_tokens=25,
                        total_tokens=40,
                    ),
                )
            ],
        )
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_PLANNER)

        messages = [ChatMessage(role=MessageRole.USER, content="Hello")]
        response = llm.chat(messages)

        assert response.additional_kwargs["token_usage"] == {
            "input_tokens": 15,
            "output_tokens": 25,
            "total_tokens": 40,
        }

    def test_chat_propagates_timeout_and_invokes_progress_callback_around_provider_call(
        self,
    ) -> None:
        """chat() renews ownership before and after one bounded provider call."""
        provider = MockModelProvider()
        progress: list[str] = []
        llm = ProofAgentLLM(
            model_provider=provider,
            role=ModelCallRole.INGESTION,
            timeout_seconds=23,
            progress_callback=lambda: progress.append("renewed"),
        )

        llm.chat([ChatMessage(role=MessageRole.USER, content="Summarize")])

        assert provider._calls[0].timeout_seconds == 23
        assert progress == ["renewed", "renewed"]

    def test_progress_callback_failure_stops_provider_call(self) -> None:
        """Ownership loss before provider invocation aborts the bounded call."""
        provider = MockModelProvider()

        def lose_ownership() -> None:
            raise RuntimeError("lease lost")

        llm = ProofAgentLLM(
            model_provider=provider,
            role=ModelCallRole.INGESTION,
            progress_callback=lose_ownership,
        )

        with pytest.raises(RuntimeError, match="lease lost"):
            llm.complete("Summarize")

        assert provider._calls == []

    def test_metadata_returns_llm_metadata(self) -> None:
        """metadata property returns LLMMetadata with correct model_name."""
        provider = MockModelProvider(
            provider_name="test_provider",
            model_name="gpt-4",
        )
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_PLANNER)

        metadata = llm.metadata

        assert metadata.model_name == "gpt-4"
        assert metadata.is_chat_model is True  # We're implementing chat interface

    def test_metadata_is_cached(self) -> None:
        """metadata property is cached and returns same instance."""
        provider = MockModelProvider()
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.INGESTION)

        metadata1 = llm.metadata
        metadata2 = llm.metadata

        assert metadata1 is metadata2

    def test_acomplete_raises_not_implemented(self) -> None:
        """acomplete() raises NotImplementedError to explicitly disable async."""
        provider = MockModelProvider()
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_PLANNER)

        with pytest.raises(NotImplementedError, match="ProofAgentLLM does not support async"):
            import asyncio

            asyncio.run(llm.acomplete("Prompt"))

    def test_achat_raises_not_implemented(self) -> None:
        """achat() raises NotImplementedError to explicitly disable async."""
        provider = MockModelProvider()
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_PLANNER)

        with pytest.raises(NotImplementedError, match="ProofAgentLLM does not support async"):
            import asyncio

            messages = [ChatMessage(role=MessageRole.USER, content="Hello")]
            asyncio.run(llm.achat(messages))

    def test_stream_complete_raises_not_implemented(self) -> None:
        """stream_complete() raises NotImplementedError to explicitly disable streaming."""
        provider = MockModelProvider()
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_PLANNER)

        with pytest.raises(NotImplementedError, match="ProofAgentLLM does not support streaming"):
            llm.stream_complete("Prompt")

    def test_stream_chat_raises_not_implemented(self) -> None:
        """stream_chat() raises NotImplementedError to explicitly disable streaming."""
        provider = MockModelProvider()
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_PLANNER)

        with pytest.raises(NotImplementedError, match="ProofAgentLLM does not support streaming"):
            messages = [ChatMessage(role=MessageRole.USER, content="Hello")]
            llm.stream_chat(messages)

    def test_provider_errors_propagate(self) -> None:
        """Errors from ModelProvider.generate() propagate to caller."""

        class ErrorProvider(MockModelProvider):
            def generate(self, request):
                raise ValueError("Provider error")

        provider = ErrorProvider()
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_PLANNER)

        with pytest.raises(ValueError, match="Provider error"):
            llm.complete("Prompt")

    def test_complete_with_formatted_flag(self) -> None:
        """complete() accepts formatted flag parameter."""
        provider = MockModelProvider()
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_PLANNER)

        # Should not raise error
        response = llm.complete("Formatted prompt", formatted=True)

        assert isinstance(response, CompletionResponse)

    def test_class_name_returns_custom_llm(self) -> None:
        """class_name() returns 'custom_llm' as expected by LlamaIndex."""
        provider = MockModelProvider()
        llm = ProofAgentLLM(model_provider=provider, role=ModelCallRole.RETRIEVAL_PLANNER)

        assert llm.class_name() == "custom_llm"
