"""ProofAgentLLM bridge adapter for LlamaIndex.

This module provides a bridge between LlamaIndex's LLM interface and Proof Agent's
ModelProvider protocol, ensuring all LLM calls go through the governed harness.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Sequence

from llama_index.core.base.llms.types import (
    ChatMessage,
    ChatResponse,
    CompletionResponse,
    LLMMetadata,
)
from llama_index.core.llms import CustomLLM, MessageRole

from proof_agent.contracts import (
    ModelCallRole,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelRole,
)

if TYPE_CHECKING:
    from proof_agent.capabilities.models.protocol import ModelProvider


# Mapping from LlamaIndex MessageRole to Proof Agent ModelRole
_ROLE_MAP = {
    MessageRole.SYSTEM: ModelRole.SYSTEM,
    MessageRole.USER: ModelRole.USER,
    MessageRole.ASSISTANT: ModelRole.ASSISTANT,
    MessageRole.TOOL: ModelRole.TOOL,
}


def _convert_message(llama_message: ChatMessage) -> ModelMessage:
    """Convert LlamaIndex ChatMessage to Proof Agent ModelMessage.

    Args:
        llama_message: LlamaIndex chat message

    Returns:
        Proof Agent model message

    Raises:
        ValueError: If message role is not supported
    """
    role_str = _ROLE_MAP.get(llama_message.role)
    if role_str is None:
        raise ValueError(f"Unsupported message role: {llama_message.role}")

    # Extract text content from message blocks
    content = ""
    if llama_message.blocks:
        for block in llama_message.blocks:
            if hasattr(block, "text"):
                content += block.text
    elif hasattr(llama_message, "content") and llama_message.content:
        # Fallback to content attribute if blocks are empty
        content = str(llama_message.content)

    return ModelMessage(
        role=role_str,
        content=content,
    )


class ProofAgentLLM(CustomLLM):
    """LlamaIndex LLM adapter that bridges to Proof Agent's ModelProvider protocol.

    This adapter ensures all LLM calls from LlamaIndex operations (tree index building,
    routing, retrieval planning) go through Proof Agent's governed ModelProvider interface,
    enabling unified tracing, policy enforcement, and token tracking.

    Only synchronous interfaces are supported. All async and streaming methods raise
    NotImplementedError to make the limitation explicit.

    Example:
        ```python
        from proof_agent.capabilities.models.llama_index_bridge import ProofAgentLLM
        from proof_agent.capabilities.models.openai_provider import OpenAIModelProvider
        from proof_agent.contracts import ModelCallRole

        provider = OpenAIModelProvider(model_name="gpt-4")
        llm = ProofAgentLLM(
            model_provider=provider,
            role=ModelCallRole.RETRIEVAL_PLANNER,
        )

        # Use with LlamaIndex
        response = llm.complete("Generate a summary")
        ```
    """

    _provider: ModelProvider
    _role: ModelCallRole
    _metadata: LLMMetadata | None
    _timeout_seconds: int | None
    _progress_callback: Callable[[], None] | None

    def __init__(
        self,
        model_provider: ModelProvider,
        role: ModelCallRole,
        timeout_seconds: int | None = None,
        progress_callback: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize ProofAgentLLM adapter.

        Args:
            model_provider: Proof Agent ModelProvider instance
            role: ModelCallRole identifying the purpose of LLM calls
            timeout_seconds: Optional bound for each provider call
            progress_callback: Optional ownership-renewal callback around provider calls
            **kwargs: Additional arguments passed to CustomLLM base class
        """
        super().__init__(**kwargs)
        self._provider = model_provider
        self._role = role
        self._metadata = None
        self._timeout_seconds = timeout_seconds
        self._progress_callback = progress_callback

    def complete(
        self,
        prompt: str,
        formatted: bool = False,
        **kwargs: Any,
    ) -> CompletionResponse:
        """Generate completion for a prompt.

        Converts the prompt to a ModelRequest with a single user message, calls
        the ModelProvider, and converts the ModelResponse to a CompletionResponse.

        Args:
            prompt: Text prompt to complete
            formatted: Whether the prompt is already formatted (ignored)
            **kwargs: Additional arguments (ignored)

        Returns:
            CompletionResponse with generated text and metadata
        """
        # Convert prompt to ModelRequest
        message = ModelMessage(role=ModelRole.USER, content=prompt)
        request = ModelRequest(
            messages=(message,),
            provider=self._provider.provider_name,
            model=self._provider.model_name,
            timeout_seconds=self._timeout_seconds,
        )

        # Call provider
        response = self._generate(request)

        # Convert to CompletionResponse
        return self._model_response_to_completion(response)

    def chat(
        self,
        messages: Sequence[ChatMessage],
        **kwargs: Any,
    ) -> ChatResponse:
        """Generate response for a chat conversation.

        Converts LlamaIndex ChatMessages to ModelRequest, calls the ModelProvider,
        and converts the ModelResponse to a ChatResponse.

        Args:
            messages: Sequence of LlamaIndex ChatMessages
            **kwargs: Additional arguments (ignored)

        Returns:
            ChatResponse with assistant message and metadata
        """
        # Convert messages
        model_messages = tuple(_convert_message(msg) for msg in messages)

        # Create ModelRequest
        request = ModelRequest(
            messages=model_messages,
            provider=self._provider.provider_name,
            model=self._provider.model_name,
            timeout_seconds=self._timeout_seconds,
        )

        # Call provider
        response = self._generate(request)

        # Convert to ChatResponse
        return self._model_response_to_chat(response)

    def stream_complete(
        self,
        prompt: str,
        formatted: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Streaming completion is not supported.

        Raises:
            NotImplementedError: Always raised to explicitly disable streaming
        """
        raise NotImplementedError(
            "ProofAgentLLM does not support streaming. Use complete() instead."
        )

    def stream_chat(
        self,
        messages: Sequence[ChatMessage],
        **kwargs: Any,
    ) -> Any:
        """Streaming chat is not supported.

        Raises:
            NotImplementedError: Always raised to explicitly disable streaming
        """
        raise NotImplementedError("ProofAgentLLM does not support streaming. Use chat() instead.")

    async def acomplete(
        self,
        prompt: str,
        formatted: bool = False,
        **kwargs: Any,
    ) -> CompletionResponse:
        """Async completion is not supported.

        Raises:
            NotImplementedError: Always raised to explicitly disable async
        """
        raise NotImplementedError(
            "ProofAgentLLM does not support async operations. Use complete() instead."
        )

    async def achat(
        self,
        messages: Sequence[ChatMessage],
        **kwargs: Any,
    ) -> ChatResponse:
        """Async chat is not supported.

        Raises:
            NotImplementedError: Always raised to explicitly disable async
        """
        raise NotImplementedError(
            "ProofAgentLLM does not support async operations. Use chat() instead."
        )

    async def astream_complete(
        self,
        prompt: str,
        formatted: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Async streaming completion is not supported.

        Raises:
            NotImplementedError: Always raised to explicitly disable async streaming
        """
        raise NotImplementedError(
            "ProofAgentLLM does not support async operations. Use complete() instead."
        )

    async def astream_chat(
        self,
        messages: Sequence[ChatMessage],
        **kwargs: Any,
    ) -> Any:
        """Async streaming chat is not supported.

        Raises:
            NotImplementedError: Always raised to explicitly disable async streaming
        """
        raise NotImplementedError(
            "ProofAgentLLM does not support async operations. Use chat() instead."
        )

    @property
    def metadata(self) -> LLMMetadata:
        """Return LLM metadata (cached).

        Returns:
            LLMMetadata with model name and capabilities
        """
        if self._metadata is None:
            self._metadata = LLMMetadata(
                model_name=self._provider.model_name,
                is_chat_model=True,
            )
        return self._metadata

    def _generate(self, request: ModelRequest) -> ModelResponse:
        self._report_progress()
        try:
            return self._provider.generate(request)
        finally:
            self._report_progress()

    def _report_progress(self) -> None:
        if self._progress_callback is not None:
            self._progress_callback()

    def _model_response_to_completion(
        self,
        response: ModelResponse,
    ) -> CompletionResponse:
        """Convert ModelResponse to LlamaIndex CompletionResponse.

        Args:
            response: Proof Agent model response

        Returns:
            LlamaIndex completion response
        """
        additional_kwargs: dict[str, Any] = {
            "provider_name": response.provider_name,
            "model_name": response.model_name,
            "role": self._role.value,
        }

        if response.token_usage:
            additional_kwargs["token_usage"] = {
                "input_tokens": response.token_usage.input_tokens,
                "output_tokens": response.token_usage.output_tokens,
                "total_tokens": response.token_usage.total_tokens,
            }

        if response.finish_reason:
            additional_kwargs["finish_reason"] = response.finish_reason

        if response.refusal_reason:
            additional_kwargs["refusal_reason"] = response.refusal_reason

        return CompletionResponse(
            text=response.content,
            additional_kwargs=additional_kwargs,
        )

    def _model_response_to_chat(
        self,
        response: ModelResponse,
    ) -> ChatResponse:
        """Convert ModelResponse to LlamaIndex ChatResponse.

        Args:
            response: Proof Agent model response

        Returns:
            LlamaIndex chat response
        """
        additional_kwargs: dict[str, Any] = {
            "provider_name": response.provider_name,
            "model_name": response.model_name,
            "role": self._role.value,
        }

        if response.token_usage:
            additional_kwargs["token_usage"] = {
                "input_tokens": response.token_usage.input_tokens,
                "output_tokens": response.token_usage.output_tokens,
                "total_tokens": response.token_usage.total_tokens,
            }

        if response.finish_reason:
            additional_kwargs["finish_reason"] = response.finish_reason

        if response.refusal_reason:
            additional_kwargs["refusal_reason"] = response.refusal_reason

        assistant_message = ChatMessage(
            role=MessageRole.ASSISTANT,
            content=response.content,
        )

        return ChatResponse(
            message=assistant_message,
            additional_kwargs=additional_kwargs,
        )
